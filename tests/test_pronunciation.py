from io import BytesIO
from threading import Event
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import listening, main, pronunciation
from app.config import Settings
from app.models import Card

LOOPBACK = {"Host": "127.0.0.1"}
POLLY_HEADERS = {**LOOPBACK, "Polly-Opt-In": "true"}
RECORD_HEADERS = {
    **LOOPBACK,
    "Recording-Consent": "true",
    "Content-Type": "audio/webm",
}
SENTENCE = "A DNS resolver caches the configured VPC CIDR block and serves SQL traffic."


@pytest.fixture(autouse=True)
def isolated_recordings(monkeypatch):
    store = pronunciation.PronunciationRecordingStore()
    monkeypatch.setattr(main, "pronunciation_recordings", store)
    try:
        yield store
    finally:
        store.clear()


@pytest.fixture
def polly(monkeypatch):
    settings = Settings(polly_enabled=True, polly_region="us-east-1", polly_voice_id="Joanna")
    monkeypatch.setattr(listening, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "listening_audio", listening.ListeningAudio())
    speech = Mock(
        side_effect=lambda **_: {"AudioStream": BytesIO(b"ref-mp3"), "ContentType": "audio/mpeg"}
    )
    factory = Mock(return_value=Mock(synthesize_speech=speech))
    monkeypatch.setattr(listening.boto3, "client", factory)
    return settings, factory, speech


def create_deck(client, name="Pronunciation deck"):
    resp = client.post("/decks", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def create_card(
    client,
    *,
    deck_id=None,
    kind="pronunciation",
    front="Shadow this networking sentence",
    back=SENTENCE,
    explanation="Keep technical acronyms clear.",
):
    if deck_id is None:
        deck_id = create_deck(client)
    return client.post(
        "/cards",
        json={
            "deck_id": deck_id,
            "kind": kind,
            "front": front,
            "back": back,
            "explanation": explanation,
        },
    )


def test_full_listen_shadow_record_replay_compare_delete_and_grade_workflow(client, polly):
    _, factory, speech = polly
    card = create_card(client).json()
    cid = card["id"]
    path = f"/study/{cid}"

    prompt = client.get(
        "/study/next", params={"deck_id": card["deck_id"], "kind": "pronunciation"}
    ).json()
    assert prompt["card_id"] == cid
    assert prompt["kind"] == "pronunciation"
    assert "back" not in prompt
    factory.assert_not_called()

    # 1. Listen (reference audio reuses Polly cache)
    audio = client.post(f"{path}/pronunciation/audio", headers=POLLY_HEADERS)
    assert audio.status_code == 200
    assert audio.headers["Content-Type"] == "audio/mpeg"
    assert audio.headers["Cache-Control"] == "no-store"
    assert audio.content == b"ref-mp3"
    assert client.post(f"{path}/pronunciation/audio", headers=POLLY_HEADERS).content == b"ref-mp3"
    factory.assert_called_once()
    speech.assert_called_once()

    # 2 & 3. Shadow + Record with explicit consent and MIME parameters
    upload = client.post(
        f"{path}/pronunciation/recording",
        headers={
            **LOOPBACK,
            "Recording-Consent": "true",
            "Content-Type": "audio/webm;codecs=opus",
        },
        content=b"learner-webm-clip",
    )
    assert upload.status_code == 201
    assert upload.json() == {
        "card_id": cid,
        "media_type": "audio/webm",
        "size_bytes": len(b"learner-webm-clip"),
        "expires_in_seconds": pronunciation.RECORDING_TTL_SECONDS,
    }

    replay = client.get(f"{path}/pronunciation/recording", headers=LOOPBACK)
    assert replay.status_code == 200
    assert replay.headers["Content-Type"] == "audio/webm"
    assert replay.headers["Cache-Control"] == "no-store"
    assert replay.content == b"learner-webm-clip"

    # 4. Compare without body uses active recording
    compared = client.post(f"{path}/pronunciation/compare", headers=LOOPBACK)
    assert compared.status_code == 200
    body = compared.json()
    assert body["card_id"] == cid
    assert body["deck_id"] == card["deck_id"]
    assert body["kind"] == "pronunciation"
    assert body["reference_text"] == SENTENCE
    assert body["card_explanation"] == "Keep technical acronyms clear."
    assert body["has_recording"] is True
    assert body["recording_status"] == "recorded"
    assert body["matched_terms"] == []
    assert body["missing_terms"] == []
    assert body["extra_terms"] == []
    assert "Replay your local recording" in body["intelligibility_focus"]
    assert len(body["workflow_steps"]) == 4
    assert body["workflow_steps"][2].startswith("3. Record:")
    assert "No numeric scores" in body["evaluation_disclaimer"]
    assert "score" not in body
    assert "percentage" not in body
    assert "cefr" not in body

    # Compare with recording + transcript + self-check note
    compared_with_text = client.post(
        f"{path}/pronunciation/compare",
        headers=LOOPBACK,
        json={
            "spoken_transcript": "A DNS resolver caches the configured VPC block and serves SQL.",
            "learner_notes": "Slow down on CIDR.",
        },
    )
    assert compared_with_text.status_code == 200
    detail = compared_with_text.json()
    assert detail["recording_status"] == "recorded"
    assert detail["has_recording"] is True
    assert "cidr" in detail["missing_terms"]
    assert "traffic" in detail["missing_terms"]
    assert detail["extra_terms"] == []
    assert "dns" in detail["matched_terms"]
    assert any("CIDR" in note for note in detail["pronunciation_notes"])
    assert any("SQL" in note for note in detail["pronunciation_notes"])
    assert any("DNS/VPC" in note for note in detail["pronunciation_notes"])
    assert any("-ed endings" in note for note in detail["pronunciation_notes"])
    assert any(
        "Card note: Keep technical acronyms clear." == n for n in detail["pronunciation_notes"]
    )
    assert any("Self-check note: Slow down on CIDR." == n for n in detail["pronunciation_notes"])

    # Delete control + idempotency
    assert client.delete(f"{path}/pronunciation/recording", headers=LOOPBACK).status_code == 204
    assert client.get(f"{path}/pronunciation/recording", headers=LOOPBACK).status_code == 404
    assert client.delete(f"{path}/pronunciation/recording", headers=LOOPBACK).status_code == 204

    # Self-grade with SM-2
    grade = client.post(f"{path}/grade", json={"quality": 4})
    assert grade.status_code == 201
    assert grade.json()["repetitions"] == 1


def test_card_eligibility_and_listening_audio_unchanged(client, polly):
    assert create_card(client, kind="pronunciation", back="x" * 1001).status_code == 422
    assert create_card(client, kind="pronunciation", back="x" * 1000).status_code == 201

    deck_id = create_deck(client, "Eligibility")
    for kind in ("pronunciation", "vocabulary", "sentence", "interview_phrase", "listening"):
        card = create_card(client, deck_id=deck_id, kind=kind, back="Check TCP stream.").json()
        cid = card["id"]
        assert (
            client.post(f"/study/{cid}/pronunciation/audio", headers=POLLY_HEADERS).status_code
            == 200
        )
        assert (
            client.post(
                f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"clip"
            ).status_code
            == 201
        )
        assert (
            client.post(f"/study/{cid}/pronunciation/compare", headers=LOOPBACK).status_code == 200
        )

    # POST /study/{card_id}/audio stays restricted to kind == "listening"
    pron = create_card(client, deck_id=deck_id, kind="pronunciation", back="Check DNS.").json()
    assert client.post(f"/study/{pron['id']}/audio", headers=POLLY_HEADERS).status_code == 409

    # Ineligible kinds return 409
    ineligible = [
        create_card(client, deck_id=deck_id, kind="behavioral", back="STAR response.").json(),
        create_card(
            client, deck_id=deck_id, kind="cloze", front="Drain the ____ pool.", back="connection"
        ).json(),
        create_card(client, deck_id=deck_id, kind="es_en", back="Roll back the release.").json(),
        create_card(client, deck_id=deck_id, kind="sentence", back="a" * 1001).json(),
    ]
    for card in ineligible:
        cid = card["id"]
        assert (
            client.post(f"/study/{cid}/pronunciation/audio", headers=POLLY_HEADERS).status_code
            == 409
        )
        assert (
            client.post(
                f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"clip"
            ).status_code
            == 409
        )
        assert (
            client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK).status_code == 409
        )
        assert (
            client.post(
                f"/study/{cid}/pronunciation/compare",
                headers=LOOPBACK,
                json={"microphone_available": False},
            ).status_code
            == 409
        )

    # Missing card returns 404 (and DELETE purges any stale entry first)
    main.pronunciation_recordings.put(
        999, deck_id, "pronunciation", "stale", "audio/webm", b"stale"
    )
    assert client.post("/study/999/pronunciation/audio", headers=POLLY_HEADERS).status_code == 404
    assert (
        client.post(
            "/study/999/pronunciation/recording", headers=RECORD_HEADERS, content=b"clip"
        ).status_code
        == 404
    )
    assert client.get("/study/999/pronunciation/recording", headers=LOOPBACK).status_code == 404
    assert (
        client.post(
            "/study/999/pronunciation/compare",
            headers=LOOPBACK,
            json={"microphone_available": False},
        ).status_code
        == 404
    )
    assert client.delete("/study/999/pronunciation/recording", headers=LOOPBACK).status_code == 404
    assert main.pronunciation_recordings.get(999, deck_id, "pronunciation", "stale") is None


def test_microphone_denied_fallback_and_intelligibility_notes(client):
    card = create_card(
        client,
        back="The server streams 'DNS' packets and don't need speed when resolved over IP.",
        explanation=None,
    ).json()
    cid = card["id"]
    path = f"/study/{cid}/pronunciation/compare"

    # microphone_available=True requires either a recording or non-empty transcript
    assert client.post(path, headers=LOOPBACK).status_code == 409
    assert client.post(path, headers=LOOPBACK, json={"spoken_transcript": "   "}).status_code == 409
    assert (
        client.post(path, headers=LOOPBACK, json={"microphone_available": "false"}).status_code
        == 422
    )
    assert (
        client.post(path, headers=LOOPBACK, json={"spoken_transcript": "bad\x00text"}).status_code
        == 422
    )

    # Transcript-only comparison without recording
    transcript_only = client.post(
        path,
        headers=LOOPBACK,
        json={
            "spoken_transcript": (
                "The server streams DNS packets and don't need speed when resolved over IP extra"
            )
        },
    )
    assert transcript_only.status_code == 200
    data = transcript_only.json()
    assert data["has_recording"] is False
    assert data["recording_status"] == "transcript_only"
    assert data["missing_terms"] == []
    assert data["extra_terms"] == ["extra"]
    assert "dns" in data["matched_terms"]
    assert "don't" in data["matched_terms"]
    assert "trim extra terms (extra)" in data["intelligibility_focus"]
    notes = data["pronunciation_notes"]
    assert any("s-clusters" in n and "'streams'" in n and "'speed'" in n for n in notes)
    assert any("-ed endings" in n and "'resolved'" in n and "'need'" not in n for n in notes)
    assert any("voiced /v/" in n and "'server'" in n for n in notes)
    assert any("DNS/IP" in n for n in notes)

    # Exact match transcript
    exact = client.post(
        path,
        headers=LOOPBACK,
        json={
            "spoken_transcript": (
                "the server streams dns packets and don't need speed when resolved over ip"
            )
        },
    ).json()
    assert exact["missing_terms"] == []
    assert exact["extra_terms"] == []
    assert "All key reference terms were captured" in exact["intelligibility_focus"]

    # Microphone-denied fallback without recording or transcript
    fallback = client.post(
        path,
        headers=LOOPBACK,
        json={"microphone_available": False, "learner_notes": "Practiced aloud twice."},
    )
    assert fallback.status_code == 200
    fb = fallback.json()
    assert fb["has_recording"] is False
    assert fb["recording_status"] == "microphone_denied_fallback"
    assert fb["matched_terms"] == []
    assert fb["missing_terms"] == []
    assert fb["extra_terms"] == []
    assert fb["intelligibility_focus"].startswith("Microphone fallback active:")
    assert fb["workflow_steps"][2].startswith("3. Microphone-denied fallback:")
    assert "Self-check note: Practiced aloud twice." in fb["pronunciation_notes"]

    # Microphone-denied fallback also works with a spoken transcript
    fallback_text = client.post(
        path,
        headers=LOOPBACK,
        json={"microphone_available": False, "spoken_transcript": "the server streams dns"},
    )
    assert fallback_text.status_code == 200
    fbt = fallback_text.json()
    assert fbt["recording_status"] == "microphone_denied_fallback"
    assert fbt["workflow_steps"][2].startswith("3. Microphone-denied fallback:")
    assert "packets" in fbt["missing_terms"]

    # Short plain word gets rhythm & pace fallback notes (at least 2 notes)
    plain = create_card(client, back="go", explanation=None).json()
    plain_cmp = client.post(
        f"/study/{plain['id']}/pronunciation/compare",
        headers=LOOPBACK,
        json={"microphone_available": False},
    ).json()
    assert pronunciation.RHYTHM_NOTE in plain_cmp["pronunciation_notes"]
    assert pronunciation.PACE_NOTE in plain_cmp["pronunciation_notes"]


def test_consent_polly_opt_in_polly_fallbacks_and_loopback_enforcement(client, polly, monkeypatch):
    settings, factory, speech = polly
    card = create_card(client).json()
    cid = card["id"]

    # Consent / opt-in headers required
    assert client.post(f"/study/{cid}/pronunciation/audio", headers=LOOPBACK).status_code == 422
    assert (
        client.post(
            f"/study/{cid}/pronunciation/audio", headers={**LOOPBACK, "Polly-Opt-In": "false"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording",
            headers={**LOOPBACK, "Content-Type": "audio/webm"},
            content=b"clip",
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording",
            headers={**LOOPBACK, "Recording-Consent": "false", "Content-Type": "audio/webm"},
            content=b"clip",
        ).status_code
        == 422
    )

    # Loopback and proxy header checks on every pronunciation endpoint
    endpoints = [
        ("POST", f"/study/{cid}/pronunciation/audio", {"Polly-Opt-In": "true"}, None),
        (
            "POST",
            f"/study/{cid}/pronunciation/recording",
            {"Recording-Consent": "true", "Content-Type": "audio/webm"},
            b"clip",
        ),
        ("GET", f"/study/{cid}/pronunciation/recording", {}, None),
        ("DELETE", f"/study/{cid}/pronunciation/recording", {}, None),
        ("DELETE", "/study/pronunciation/recordings", {}, None),
        ("POST", f"/study/{cid}/pronunciation/compare", {}, None),
    ]
    for method, url, extra_headers, content in endpoints:
        # Non-loopback Host header (default TestClient host is "testserver")
        assert (
            client.request(method, url, headers=extra_headers, content=content).status_code == 403
        )
        # X-Forwarded-For rejected
        assert (
            client.request(
                method,
                url,
                headers={**LOOPBACK, **extra_headers, "X-Forwarded-For": "192.0.2.5"},
                content=content,
            ).status_code
            == 403
        )
        # Forwarded header rejected
        assert (
            client.request(
                method,
                url,
                headers={**LOOPBACK, **extra_headers, "Forwarded": "for=192.0.2.5"},
                content=content,
            ).status_code
            == 403
        )
        # Non-loopback remote client IP rejected
        with TestClient(main.app, client=("192.0.2.5", 50000)) as remote:
            assert (
                remote.request(
                    method, url, headers={**LOOPBACK, **extra_headers}, content=content
                ).status_code
                == 403
            )

    # IPv6 loopback and Host: localhost are accepted
    with TestClient(main.app, client=("::1", 50000)) as ipv6_client:
        resp = ipv6_client.post(
            f"/study/{cid}/pronunciation/compare",
            headers={"Host": "localhost"},
            json={"microphone_available": False},
        )
        assert resp.status_code == 200

    # Polly disabled -> 503 with clear text-only fallback guidance
    settings.polly_enabled = False
    disabled = client.post(f"/study/{cid}/pronunciation/audio", headers=POLLY_HEADERS)
    assert disabled.status_code == 503
    assert "/pronunciation/compare" in disabled.json()["detail"]
    assert "/reveal" in disabled.json()["detail"]
    factory.assert_not_called()

    # Polly failure & budget exhaustion -> 503 then 429
    settings.polly_enabled = True
    monkeypatch.setattr(listening, "SYNTHESIS_ATTEMPTS_PER_HOUR", 1)
    speech.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "SynthesizeSpeech"
    )
    failed = client.post(f"/study/{cid}/pronunciation/audio", headers=POLLY_HEADERS)
    assert failed.status_code == 503
    assert "/pronunciation/compare" in failed.json()["detail"]
    exhausted = client.post(f"/study/{cid}/pronunciation/audio", headers=POLLY_HEADERS)
    assert exhausted.status_code == 429
    assert "/pronunciation/compare" in exhausted.json()["detail"]


def test_recording_media_types_size_bounds_ttl_and_lru_eviction(client, monkeypatch):
    card = create_card(client).json()
    cid = card["id"]
    url = f"/study/{cid}/pronunciation/recording"

    # Unsupported media types -> 415
    for bad_ct in ("text/plain", "application/octet-stream", ""):
        headers = {**LOOPBACK, "Recording-Consent": "true"}
        if bad_ct:
            headers["Content-Type"] = bad_ct
        assert client.post(url, headers=headers, content=b"data").status_code == 415

    # All supported media types -> 201
    for mime in sorted(pronunciation.ALLOWED_RECORDING_TYPES):
        resp = client.post(
            url,
            headers={**LOOPBACK, "Recording-Consent": "true", "Content-Type": mime},
            content=b"ok",
        )
        assert resp.status_code == 201
        assert resp.json()["media_type"] == mime

    # Empty -> 422, exact 512 KiB -> 201, > 512 KiB -> 413
    assert client.post(url, headers=RECORD_HEADERS, content=b"").status_code == 422
    max_bytes = b"a" * pronunciation.MAX_RECORDING_BYTES
    ok_max = client.post(url, headers=RECORD_HEADERS, content=max_bytes)
    assert ok_max.status_code == 201
    assert ok_max.json()["size_bytes"] == pronunciation.MAX_RECORDING_BYTES
    assert client.post(url, headers=RECORD_HEADERS, content=max_bytes + b"x").status_code == 413

    # TTL expiry
    now = 1000.0
    monkeypatch.setattr(pronunciation, "monotonic", lambda: now)
    assert client.post(url, headers=RECORD_HEADERS, content=b"timed").status_code == 201
    now += pronunciation.RECORDING_TTL_SECONDS - 1
    assert client.get(url, headers=LOOPBACK).status_code == 200
    now += 1
    assert client.get(url, headers=LOOPBACK).status_code == 404
    assert client.post(f"/study/{cid}/pronunciation/compare", headers=LOOPBACK).status_code == 409

    # LRU eviction
    monkeypatch.setattr(pronunciation, "MAX_RECORDINGS", 2)
    deck_id = card["deck_id"]
    c1 = create_card(client, deck_id=deck_id, back="First phrase.").json()["id"]
    c2 = create_card(client, deck_id=deck_id, back="Second phrase.").json()["id"]
    c3 = create_card(client, deck_id=deck_id, back="Third phrase.").json()["id"]
    assert (
        client.post(
            f"/study/{c1}/pronunciation/recording", headers=RECORD_HEADERS, content=b"1"
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/study/{c2}/pronunciation/recording", headers=RECORD_HEADERS, content=b"2"
        ).status_code
        == 201
    )
    # Access c1 so c2 becomes least recently used
    assert client.get(f"/study/{c1}/pronunciation/recording", headers=LOOPBACK).content == b"1"
    assert (
        client.post(
            f"/study/{c3}/pronunciation/recording", headers=RECORD_HEADERS, content=b"3"
        ).status_code
        == 201
    )
    assert client.get(f"/study/{c1}/pronunciation/recording", headers=LOOPBACK).content == b"1"
    assert client.get(f"/study/{c2}/pronunciation/recording", headers=LOOPBACK).status_code == 404
    assert client.get(f"/study/{c3}/pronunciation/recording", headers=LOOPBACK).content == b"3"


def test_recording_invalidation_on_card_deck_error_mutations_and_bulk_clear(client):
    deck_a = create_deck(client, "Deck A")
    deck_b = create_deck(client, "Deck B")
    card = create_card(client, deck_id=deck_a, back="Original sentence.").json()
    cid = card["id"]

    # Upload recording; editing front/explanation only keeps the clip
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"v1"
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/cards/{cid}",
            json={
                "deck_id": deck_a,
                "kind": "pronunciation",
                "front": "Updated prompt",
                "back": "Original sentence.",
                "explanation": "Updated note",
            },
        ).status_code
        == 200
    )
    assert client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK).content == b"v1"

    # Changing back invalidates recording
    assert (
        client.put(
            f"/cards/{cid}",
            json={
                "deck_id": deck_a,
                "kind": "pronunciation",
                "front": "Updated prompt",
                "back": "Edited sentence.",
            },
        ).status_code
        == 200
    )
    assert client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK).status_code == 404

    # Changing kind invalidates recording
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"v2"
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/cards/{cid}",
            json={
                "deck_id": deck_a,
                "kind": "sentence",
                "front": "Updated prompt",
                "back": "Edited sentence.",
            },
        ).status_code
        == 200
    )
    assert client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK).status_code == 404

    # Moving card to another deck invalidates recording
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"v3"
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/cards/{cid}",
            json={
                "deck_id": deck_b,
                "kind": "sentence",
                "front": "Updated prompt",
                "back": "Edited sentence.",
            },
        ).status_code
        == 200
    )
    assert client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK).status_code == 404

    # Direct store verification for deck_id, kind, and reference_text mismatches
    # Mismatched reads must return None without deleting the stored recording.
    main.pronunciation_recordings.put(
        cid, deck_b, "sentence", "Edited sentence.", "audio/webm", b"direct"
    )
    assert main.pronunciation_recordings.get(cid, deck_a, "sentence", "Edited sentence.") is None
    assert (
        main.pronunciation_recordings.get(cid, deck_b, "pronunciation", "Edited sentence.") is None
    )
    assert main.pronunciation_recordings.get(cid, deck_b, "sentence", "Different text.") is None
    assert main.pronunciation_recordings.get(cid, deck_b, "sentence", "Edited sentence.") == (
        "audio/webm",
        b"direct",
    )

    # DELETE /cards/{card_id} purges recording
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"v4"
        ).status_code
        == 201
    )
    assert client.delete(f"/cards/{cid}").status_code == 204
    assert main.pronunciation_recordings.get(cid, deck_b, "sentence", "Edited sentence.") is None

    # DELETE /decks/{deck_id} purges recordings only in that deck
    c_a = create_card(client, deck_id=deck_a, back="Deck A card.").json()["id"]
    c_b = create_card(client, deck_id=deck_b, back="Deck B card.").json()["id"]
    assert (
        client.post(
            f"/study/{c_a}/pronunciation/recording", headers=RECORD_HEADERS, content=b"a"
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/study/{c_b}/pronunciation/recording", headers=RECORD_HEADERS, content=b"b"
        ).status_code
        == 201
    )
    assert client.delete(f"/decks/{deck_a}").status_code == 204
    assert main.pronunciation_recordings.get(c_a, deck_a, "pronunciation", "Deck A card.") is None
    assert client.get(f"/study/{c_b}/pronunciation/recording", headers=LOOPBACK).content == b"b"

    # DELETE /errors/{error_id}?delete_card=false keeps clip; delete_card=true purges clip
    err1 = client.post(
        "/errors",
        json={
            "attempted": "DNS is TCP only.",
            "corrected": "DNS uses UDP for standard queries and TCP for large responses.",
            "rationale": "Explain both transports.",
        },
    ).json()
    approved1 = client.post(
        f"/errors/{err1['id']}/approve", json={"deck_id": deck_b, "kind": "pronunciation"}
    ).json()
    ec1 = approved1["card"]["id"]
    assert (
        client.post(
            f"/study/{ec1}/pronunciation/recording", headers=RECORD_HEADERS, content=b"err1"
        ).status_code
        == 201
    )
    assert client.delete(f"/errors/{err1['id']}").status_code == 204
    assert client.get(f"/study/{ec1}/pronunciation/recording", headers=LOOPBACK).content == b"err1"

    err2 = client.post(
        "/errors",
        json={
            "attempted": "CIDR is a router.",
            "corrected": "CIDR stands for Classless Inter-Domain Routing.",
            "rationale": "Define CIDR accurately.",
        },
    ).json()
    approved2 = client.post(
        f"/errors/{err2['id']}/approve", json={"deck_id": deck_b, "kind": "pronunciation"}
    ).json()
    ec2 = approved2["card"]["id"]
    ec2_back = approved2["card"]["back"]
    assert (
        client.post(
            f"/study/{ec2}/pronunciation/recording", headers=RECORD_HEADERS, content=b"err2"
        ).status_code
        == 201
    )
    assert client.delete(f"/errors/{err2['id']}", params={"delete_card": "true"}).status_code == 204
    assert main.pronunciation_recordings.get(ec2, deck_b, "pronunciation", ec2_back) is None

    # Bulk clear removes all remaining recordings
    assert client.delete("/study/pronunciation/recordings", headers=LOOPBACK).status_code == 204
    assert client.get(f"/study/{c_b}/pronunciation/recording", headers=LOOPBACK).status_code == 404
    assert client.get(f"/study/{ec1}/pronunciation/recording", headers=LOOPBACK).status_code == 404


def test_recording_upload_revalidates_card_after_streaming_toctou(client, db_engine):
    card = create_card(client, back="Check TOCTOU safety.").json()
    cid = card["id"]

    def body_that_deletes_card_mid_stream():
        yield b"first-chunk"
        with Session(db_engine) as other_session:
            row = other_session.get(Card, cid)
            assert row is not None
            other_session.delete(row)
            other_session.commit()
        yield b"-second-chunk"

    resp = client.post(
        f"/study/{cid}/pronunciation/recording",
        headers=RECORD_HEADERS,
        content=body_that_deletes_card_mid_stream(),
    )
    assert resp.status_code == 404
    assert (
        main.pronunciation_recordings.get(cid, card["deck_id"], card["kind"], card["back"]) is None
    )
    assert main.pronunciation_recordings.total_bytes == 0


def test_recording_upload_rejects_card_edits_during_stream_and_put_window(
    client, db_engine, isolated_recordings, monkeypatch
):
    deck_a = create_deck(client, "TOCTOU Deck A")
    deck_b = create_deck(client, "TOCTOU Deck B")

    # 1. Changing back mid-stream rejects upload with 409 and stores nothing
    card_back = create_card(client, deck_id=deck_a, back="Original reference.").json()
    cid_back = card_back["id"]

    def body_that_edits_back():
        yield b"part-1"
        with Session(db_engine) as other_session:
            row = other_session.get(Card, cid_back)
            assert row is not None
            row.back = "Mutated reference."
            other_session.commit()
        yield b"-part-2"

    resp_back = client.post(
        f"/study/{cid_back}/pronunciation/recording",
        headers=RECORD_HEADERS,
        content=body_that_edits_back(),
    )
    assert resp_back.status_code == 409
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings.total_bytes == 0
    assert (
        client.get(f"/study/{cid_back}/pronunciation/recording", headers=LOOPBACK).status_code
        == 404
    )

    # 2. Changing kind only (still pronunciation-eligible) mid-stream rejects upload with 409
    card_kind = create_card(
        client, deck_id=deck_a, kind="pronunciation", back="Same reference text."
    ).json()
    cid_kind = card_kind["id"]

    def body_that_edits_kind():
        yield b"part-1"
        with Session(db_engine) as other_session:
            row = other_session.get(Card, cid_kind)
            assert row is not None
            row.kind = "sentence"
            other_session.commit()
        yield b"-part-2"

    resp_kind = client.post(
        f"/study/{cid_kind}/pronunciation/recording",
        headers=RECORD_HEADERS,
        content=body_that_edits_kind(),
    )
    assert resp_kind.status_code == 409
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings.total_bytes == 0
    assert (
        client.get(f"/study/{cid_kind}/pronunciation/recording", headers=LOOPBACK).status_code
        == 404
    )

    # 3. Changing deck_id mid-stream rejects upload with 409
    card_deck = create_card(client, deck_id=deck_a, back="Deck move reference.").json()
    cid_deck = card_deck["id"]

    def body_that_moves_deck():
        yield b"part-1"
        with Session(db_engine) as other_session:
            row = other_session.get(Card, cid_deck)
            assert row is not None
            row.deck_id = deck_b
            other_session.commit()
        yield b"-part-2"

    resp_deck = client.post(
        f"/study/{cid_deck}/pronunciation/recording",
        headers=RECORD_HEADERS,
        content=body_that_moves_deck(),
    )
    assert resp_deck.status_code == 409
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings.total_bytes == 0

    # 4. Concurrent delete(card_id) in the window after fresh_card check and before store.put()
    card_race = create_card(client, deck_id=deck_a, back="Race window check.").json()
    cid_race = card_race["id"]
    real_put = isolated_recordings.put

    def put_after_concurrent_invalidation(*args, **kwargs):
        isolated_recordings.delete(cid_race)
        return real_put(*args, **kwargs)

    monkeypatch.setattr(isolated_recordings, "put", put_after_concurrent_invalidation)
    resp_race = client.post(
        f"/study/{cid_race}/pronunciation/recording",
        headers=RECORD_HEADERS,
        content=b"stale-race-audio",
    )
    assert resp_race.status_code == 409
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings.total_bytes == 0

    # 5. Direct store upload_token invalidation across delete_deck and clear
    monkeypatch.setattr(isolated_recordings, "put", real_put)
    with isolated_recordings.track_upload(cid_race) as token:
        isolated_recordings.bind_upload_deck(token, deck_a)
        isolated_recordings.delete_deck(deck_a)
        assert not isolated_recordings.put(
            cid_race,
            deck_a,
            "pronunciation",
            "Race window check.",
            "audio/webm",
            b"x",
            upload_token=token,
        )
    with isolated_recordings.track_upload(cid_race) as token:
        isolated_recordings.bind_upload_deck(token, deck_a)
        isolated_recordings.clear()
        assert not isolated_recordings.put(
            cid_race,
            deck_a,
            "pronunciation",
            "Race window check.",
            "audio/webm",
            b"x",
            upload_token=token,
        )
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings.total_bytes == 0


def test_stale_reader_mismatch_preserves_newer_recording(client, isolated_recordings):
    deck_a = create_deck(client, "Stale Reader Deck A")
    deck_b = create_deck(client, "Stale Reader Deck B")
    card = create_card(
        client,
        deck_id=deck_a,
        kind="pronunciation",
        back="Snapshot A reference.",
    ).json()
    cid = card["id"]

    # Recording uploaded for snapshot A
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"audio-a"
        ).status_code
        == 201
    )

    # Card edited to snapshot B (purges A) and new recording uploaded for B
    assert (
        client.put(
            f"/cards/{cid}",
            json={
                "deck_id": deck_b,
                "kind": "sentence",
                "front": card["front"],
                "back": "Snapshot B reference.",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/study/{cid}/pronunciation/recording", headers=RECORD_HEADERS, content=b"audio-b"
        ).status_code
        == 201
    )

    # Paused reader resumes with stale snapshot A: gets None, must not delete recording B
    assert isolated_recordings.get(cid, deck_a, "pronunciation", "Snapshot A reference.") is None

    # Subsequent reader with current snapshot B still retrieves recording B
    assert isolated_recordings.get(cid, deck_b, "sentence", "Snapshot B reference.") == (
        "audio/webm",
        b"audio-b",
    )
    replay = client.get(f"/study/{cid}/pronunciation/recording", headers=LOOPBACK)
    assert replay.status_code == 200
    assert replay.content == b"audio-b"
    assert isolated_recordings.total_bytes == len(b"audio-b")


def test_idle_recording_expiration_purges_ram_without_requests(
    client, isolated_recordings, monkeypatch
):
    deck_id = create_deck(client, "Idle TTL")
    c1 = create_card(client, deck_id=deck_id, back="First idle clip.").json()["id"]
    c2 = create_card(client, deck_id=deck_id, back="Second idle clip.").json()["id"]

    payload1 = b"first-idle-audio-bytes"
    payload2 = b"second-idle-audio-bytes"
    purge_runs = 0
    uploads_done = False
    all_purged = Event()
    real_run = isolated_recordings._run_scheduled_purge

    def tracked_run(generation: int) -> None:
        nonlocal purge_runs
        purge_runs += 1
        real_run(generation)
        with isolated_recordings._lock:
            if (
                uploads_done
                and len(isolated_recordings._recordings) == 0
                and isolated_recordings._total_bytes == 0
                and isolated_recordings._expiry_timer is None
            ):
                all_purged.set()

    monkeypatch.setattr(isolated_recordings, "_run_scheduled_purge", tracked_run)

    monkeypatch.setattr(pronunciation, "RECORDING_TTL_SECONDS", 0.05)
    assert (
        client.post(
            f"/study/{c1}/pronunciation/recording", headers=RECORD_HEADERS, content=payload1
        ).status_code
        == 201
    )
    monkeypatch.setattr(pronunciation, "RECORDING_TTL_SECONDS", 0.12)
    assert (
        client.post(
            f"/study/{c2}/pronunciation/recording", headers=RECORD_HEADERS, content=payload2
        ).status_code
        == 201
    )

    with isolated_recordings._lock:
        uploads_done = True
        if (
            len(isolated_recordings._recordings) == 0
            and isolated_recordings._total_bytes == 0
            and isolated_recordings._expiry_timer is None
        ):
            all_purged.set()

    # Wait passively without issuing any GET/POST/DELETE request; background timer purges RAM.
    assert all_purged.wait(timeout=5.0)
    assert purge_runs >= 1
    assert len(isolated_recordings._recordings) == 0
    assert isolated_recordings._total_bytes == 0
    assert isolated_recordings._expiry_timer is None
