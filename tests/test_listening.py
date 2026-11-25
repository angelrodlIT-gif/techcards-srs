from io import BytesIO
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from app import listening, main
from app.config import Settings

OPT_IN = {"Host": "127.0.0.1", "Polly-Opt-In": "true"}
TRANSCRIPT = "A resolver caches a DNS answer until its time to live expires."


@pytest.fixture
def polly(monkeypatch):
    settings = Settings(polly_enabled=True, polly_region="us-east-1", polly_voice_id="Joanna")
    monkeypatch.setattr(listening, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "listening_audio", listening.ListeningAudio())
    speech = Mock(
        side_effect=lambda **_: {"AudioStream": BytesIO(b"mock-mp3"), "ContentType": "audio/mpeg"}
    )
    factory = Mock(return_value=Mock(synthesize_speech=speech))
    monkeypatch.setattr(listening.boto3, "client", factory)
    return settings, factory, speech


def create_card(client, *, kind="listening", back=TRANSCRIPT):
    deck_id = client.post("/decks", json={"name": "Network listening"}).json()["id"]
    return client.post(
        "/cards",
        json={
            "deck_id": deck_id,
            "kind": kind,
            "front": "What does a resolver cache?",
            "back": back,
        },
    )


def test_listen_replay_reveal_and_grade(client, polly):
    _, factory, speech = polly
    card = create_card(client).json()
    path = f"/study/{card['id']}"
    prompt = client.get("/study/next", params={"deck_id": card["deck_id"]}).json()
    assert prompt["kind"] == "listening"
    assert TRANSCRIPT not in str(prompt)
    assert "back" not in prompt
    factory.assert_not_called()

    for card_id in (card["id"], card["id"], create_card(client).json()["id"]):
        audio = client.post(f"/study/{card_id}/audio", headers=OPT_IN)
        assert audio.status_code == 200
        assert audio.headers["Content-Type"] == "audio/mpeg"
        assert audio.headers["Cache-Control"] == "no-store"
        assert audio.content == b"mock-mp3"
    factory.assert_called_once()
    args, kwargs = factory.call_args
    assert args == ("polly",)
    assert kwargs["region_name"] == "us-east-1"
    assert kwargs["config"].retries["total_max_attempts"] == 1
    speech.assert_called_once_with(
        Text=TRANSCRIPT,
        TextType="text",
        Engine="standard",
        LanguageCode="en-US",
        VoiceId="Joanna",
        OutputFormat="mp3",
    )

    assert client.post(f"{path}/reveal").json()["back"] == TRANSCRIPT
    grade = client.post(f"{path}/grade", json={"quality": 4})
    assert grade.status_code == 201
    assert grade.json()["repetitions"] == 1


def test_audio_requires_opt_in_local_host_and_eligible_card(client, polly):
    settings, factory, _ = polly
    card = create_card(client).json()
    path = f"/study/{card['id']}"
    assert client.post(f"{path}/audio", headers={"Host": "127.0.0.1"}).status_code == 422
    assert client.post(f"{path}/audio", headers={"Polly-Opt-In": "true"}).status_code == 403
    assert client.post("/study/999/audio", headers=OPT_IN).status_code == 404
    plain = create_card(client, kind="sentence").json()
    assert client.post(f"/study/{plain['id']}/audio", headers=OPT_IN).status_code == 409
    assert create_card(client, back="x" * 1001).status_code == 422
    assert create_card(client, back="x" * 1000).status_code == 201

    settings.polly_enabled = False
    assert client.post(f"{path}/audio", headers=OPT_IN).status_code == 503
    assert client.post(f"{path}/reveal").json()["back"] == TRANSCRIPT
    settings.polly_enabled = True
    settings.polly_region = ""
    assert client.post(f"{path}/audio", headers=OPT_IN).status_code == 503
    factory.assert_not_called()


def test_polly_failures_use_fallback_and_count_towards_budget(client, polly, monkeypatch):
    _, factory, speech = polly
    now = 0
    monkeypatch.setattr(listening, "monotonic", lambda: now)
    monkeypatch.setattr(listening, "SYNTHESIS_ATTEMPTS_PER_HOUR", 2)
    card = create_card(client).json()
    path = f"/study/{card['id']}"
    factory.side_effect = [NoCredentialsError(), factory.return_value, factory.return_value]
    speech.side_effect = [
        ClientError({"Error": {"Code": "AccessDenied", "Message": "internal"}}, "SynthesizeSpeech"),
        {"AudioStream": BytesIO(b"recovered"), "ContentType": "audio/mpeg"},
    ]

    for _ in range(2):
        response = client.post(f"{path}/audio", headers=OPT_IN)
        assert response.status_code == 503
        assert response.json() == {"detail": "Audio unavailable. Reveal for the transcript."}
    assert client.post(f"{path}/audio", headers=OPT_IN).status_code == 429
    assert factory.call_count == 2
    assert client.post(f"{path}/reveal").json()["back"] == TRANSCRIPT

    now = 3600
    assert client.post(f"{path}/audio", headers=OPT_IN).content == b"recovered"


def test_cache_expires_and_ignores_old_transcript_after_edit(client, polly, monkeypatch):
    _, _, speech = polly
    now = 0
    monkeypatch.setattr(listening, "monotonic", lambda: now)
    card = create_card(client).json()
    path = f"/study/{card['id']}/audio"
    assert client.post(path, headers=OPT_IN).status_code == 200
    now = 86400
    assert client.post(path, headers=OPT_IN).status_code == 200
    assert speech.call_count == 2

    new_transcript = "A DNS resolver queries authoritative servers."
    update = client.put(
        f"/cards/{card['id']}",
        json={**card, "back": new_transcript},
    )
    assert update.status_code == 200
    assert client.post(path, headers=OPT_IN).status_code == 200
    assert speech.call_args.kwargs["Text"] == new_transcript
    assert speech.call_count == 3
