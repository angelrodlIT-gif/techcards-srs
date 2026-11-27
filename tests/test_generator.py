import concurrent.futures
import http.client
import io
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.config import Settings, get_settings
from app.db import get_db
from app.generator import (
    MAX_CONCURRENT_DNS_LOOKUPS,
    MAX_CONCURRENT_GENERATIONS,
    MAX_RESPONSE_BYTES,
    GeneratedCard,
    GeneratorBusyError,
    GeneratorConfigError,
    GeneratorInputError,
    GeneratorTimeoutError,
    GeneratorUpstreamError,
    MockGenerator,
    OpenAICompatibleGenerator,
    _connect_with_deadline,
    _DeadlineHTTPConnection,
    _DeadlineHTTPHandler,
    _DeadlineHTTPSConnection,
    _DeadlineHTTPSHandler,
    _DeadlineSocket,
    _default_urlopen,
    _NoRedirectHandler,
    get_generator,
    validate_generator_base_url,
)
from app.main import app
from app.models import Base, Card, Deck


def _chat_completion_bytes(content: object) -> bytes:
    message_content = content if isinstance(content, str) else json.dumps(content)
    return json.dumps({"choices": [{"message": {"content": message_content}}]}).encode("utf-8")


def _make_opener(body: bytes):
    captured: list[tuple[urllib.request.Request, float]] = []

    def opener(request: urllib.request.Request, timeout: float):
        captured.append((request, timeout))
        return io.BytesIO(body)

    return opener, captured


def _clear_generator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GENERATOR_PROVIDER",
        "GENERATOR_API_KEY",
        "GENERATOR_MODEL",
        "GENERATOR_BASE_URL",
        "GENERATOR_TIMEOUT_SECONDS",
        "GENERATOR_MAX_INPUT_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


def _create_deck(client) -> int:
    response = client.post("/decks", json={"name": "AI Opt-In Test"})
    assert response.status_code == 201
    return response.json()["id"]


def test_default_provider_is_offline_mock(monkeypatch):
    _clear_generator_env(monkeypatch)

    def fail_network(*args, **kwargs):
        raise AssertionError("network must never be called in mock mode")

    monkeypatch.setattr(urllib.request, "urlopen", fail_network)
    monkeypatch.setattr(urllib.request, "build_opener", fail_network)

    try:
        generator = get_generator()
        assert isinstance(generator, MockGenerator)
        cards = generator.generate("AWS Python Linux troubleshooting role", 4)
        assert len(cards) == 4
    finally:
        get_settings.cache_clear()


def test_opt_in_provider_selection_and_secret_redaction(monkeypatch):
    _clear_generator_env(monkeypatch)
    secret = "sk-test-super-secret-token-987654"
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai_compatible")
    monkeypatch.setenv("GENERATOR_API_KEY", secret)
    monkeypatch.setenv("GENERATOR_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("GENERATOR_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("GENERATOR_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("GENERATOR_MAX_INPUT_CHARS", "1500")
    get_settings.cache_clear()

    try:
        generator = get_generator()
        assert isinstance(generator, OpenAICompatibleGenerator)
        assert generator.model == "gpt-4o-mini"
        assert generator.base_url == "http://127.0.0.1:11434/v1"
        assert generator.endpoint_url == "http://127.0.0.1:11434/v1/chat/completions"
        assert generator.timeout_seconds == 12.5
        assert generator.max_input_chars == 1500
        assert secret not in repr(generator)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("env_overrides", "expected_fragment"),
    [
        ({"GENERATOR_PROVIDER": "unknown_llm"}, "generator_provider"),
        ({"GENERATOR_PROVIDER": "openai_compatible"}, "GENERATOR_API_KEY"),
        (
            {"GENERATOR_PROVIDER": "openai_compatible", "GENERATOR_API_KEY": "   "},
            "GENERATOR_API_KEY",
        ),
        (
            {"GENERATOR_PROVIDER": "openai_compatible", "GENERATOR_API_KEY": "sk-test"},
            "GENERATOR_MODEL",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "   ",
            },
            "GENERATOR_MODEL",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_BASE_URL": "http://api.openai.com/v1",
            },
            "https://",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_TIMEOUT_SECONDS": "0",
            },
            "GENERATOR_TIMEOUT_SECONDS",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_TIMEOUT_SECONDS": "invalid",
            },
            "GENERATOR_TIMEOUT_SECONDS",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_TIMEOUT_SECONDS": "nan",
            },
            "GENERATOR_TIMEOUT_SECONDS",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_MAX_INPUT_CHARS": "9",
            },
            "GENERATOR_MAX_INPUT_CHARS",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_MAX_INPUT_CHARS": "invalid",
            },
            "GENERATOR_MAX_INPUT_CHARS",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_MAX_INPUT_CHARS": "12.5",
            },
            "GENERATOR_MAX_INPUT_CHARS",
        ),
    ],
)
def test_misconfigured_provider_fails_without_mock_fallback(
    monkeypatch, env_overrides, expected_fragment
):
    _clear_generator_env(monkeypatch)
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    try:
        with pytest.raises(GeneratorConfigError) as exc_info:
            get_generator()
        assert exc_info.value.status_code == 503
        assert expected_fragment in str(exc_info.value)
    finally:
        get_settings.cache_clear()


def test_settings_rejects_unsupported_provider_directly(monkeypatch):
    _clear_generator_env(monkeypatch)
    monkeypatch.setenv("GENERATOR_PROVIDER", "unsupported")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "ai_env_overrides",
    [
        {"GENERATOR_TIMEOUT_SECONDS": "0"},
        {"GENERATOR_TIMEOUT_SECONDS": "invalid"},
        {"GENERATOR_MAX_INPUT_CHARS": "0"},
        {"GENERATOR_MAX_INPUT_CHARS": "invalid"},
        {"GENERATOR_TIMEOUT_SECONDS": "0", "GENERATOR_MAX_INPUT_CHARS": "5"},
    ],
)
def test_mock_provider_ignores_invalid_ai_only_settings(client, monkeypatch, ai_env_overrides):
    _clear_generator_env(monkeypatch)
    monkeypatch.setenv("GENERATOR_PROVIDER", "mock")
    for key, value in ai_env_overrides.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.generator_provider == "mock"
        generator = get_generator()
        assert isinstance(generator, MockGenerator)

        did = _create_deck(client)
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role", "max_cards": 3},
        )
        assert res.status_code == 201
        assert len(res.json()) == 3
    finally:
        _clear_generator_env(monkeypatch)


@pytest.mark.parametrize(
    ("raw_url", "expected_base"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1/chat/completions",
        ),
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),
        ("http://localhost:8080/v1/", "http://localhost:8080/v1"),
        ("http://LOCALHOST:8080/v1", "http://LOCALHOST:8080/v1"),
    ],
)
def test_validate_generator_base_url_allows_https_and_loopback_http(raw_url, expected_base):
    assert validate_generator_base_url(raw_url) == expected_base


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "   ",
        "http://api.openai.com/v1",
        "http://10.0.0.5:8080/v1",
        "http://127.0.0.1.evil.com/v1",
        "http://localhost.evil.com/v1",
        "ftp://api.openai.com/v1",
        "file:///etc/passwd",
        "https://user:supersecret@api.openai.com/v1",
        "https://api.openai.com/v1?key=secret",
        "https://api.openai.com/v1#fragment",
        "https://api.openai.com/v1?",
        "https://api.openai.com/v1#",
        "https://api.openai.com:99999/v1",
        "https://api.openai.com:0/v1",
        "https://api.openai.com/v1\nX-Injected: 1",
        "https://[invalid/v1",
        "http://[::1/v1",
    ],
)
def test_validate_generator_base_url_rejects_unsafe_urls(bad_url):
    with pytest.raises(GeneratorConfigError) as exc_info:
        validate_generator_base_url(bad_url)
    assert "supersecret" not in str(exc_info.value)
    assert "key=secret" not in str(exc_info.value)


def test_constructor_rejects_control_chars_and_invalid_bounds():
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(api_key="sk-123\r\nX-Evil: 1", model="gpt-4o-mini")
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(api_key="sk-123", model="gpt-4o\nmini")
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(api_key="sk-123", model="gpt-4o-mini", timeout_seconds=0)
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(
            api_key="sk-123", model="gpt-4o-mini", timeout_seconds=float("inf")
        )
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(api_key="sk-123", model="gpt-4o-mini", max_input_chars=5)
    with pytest.raises(GeneratorConfigError):
        OpenAICompatibleGenerator(api_key="sk-123", model="gpt-4o-mini", max_input_chars=20001)


def test_openai_compatible_generator_request_and_parsing():
    body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "  Explain idempotency in REST APIs.  ",
                    "back": "  Repeating the same request produces the same server state.  ",
                    "kind": "vocabulary",
                },
                {
                    "front": "How do you explain a rollback during an interview?",
                    "back": "Practice: Describe the trigger, rollback step, and real outcome.",
                    "kind": "interview_phrase",
                },
                {
                    "front": "Tell me about an incident you debugged under pressure.",
                    "back": "Use STAR with a truthful example; do not fabricate results.",
                    "kind": "behavioral",
                },
            ]
        }
    )
    opener, captured = _make_opener(body)
    generator = OpenAICompatibleGenerator(
        api_key="sk-unit-secret",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1/",
        timeout_seconds=15.0,
        max_input_chars=500,
        opener=opener,
    )

    cards = generator.generate("  REST API rollback and incident response practice  ", max_cards=2)

    assert len(cards) == 2
    assert cards == [
        GeneratedCard(
            front="Explain idempotency in REST APIs.",
            back="Repeating the same request produces the same server state.",
            kind="vocabulary",
        ),
        GeneratedCard(
            front="How do you explain a rollback during an interview?",
            back="Practice: Describe the trigger, rollback step, and real outcome.",
            kind="interview_phrase",
        ),
    ]
    assert len(captured) == 1
    req, timeout = captured[0]
    assert req.full_url == "https://api.openai.com/v1/chat/completions"
    assert req.get_method() == "POST"
    assert timeout == 15.0
    assert req.get_header("Authorization") == "Bearer sk-unit-secret"
    assert req.get_header("Content-type") == "application/json"
    sent = json.loads(req.data.decode("utf-8"))
    assert sent["model"] == "gpt-4o-mini"
    assert sent["response_format"] == {"type": "json_object"}
    assert "STAR" in sent["messages"][0]["content"]
    assert "never fabricate" in sent["messages"][0]["content"]
    assert "REST API rollback and incident response practice" in sent["messages"][1]["content"]


def test_input_bounds_enforced_before_outbound_request():
    called = 0

    def opener(request, timeout):
        nonlocal called
        called += 1
        return io.BytesIO(b"")

    generator = OpenAICompatibleGenerator(
        api_key="sk-unit-secret",
        model="gpt-4o-mini",
        max_input_chars=50,
        opener=opener,
    )

    with pytest.raises(GeneratorInputError):
        generator.generate("x" * 51, max_cards=2)
    with pytest.raises(GeneratorInputError):
        generator.generate("short", max_cards=2)
    with pytest.raises(GeneratorInputError):
        generator.generate("valid text with\x00nul", max_cards=2)
    with pytest.raises(GeneratorInputError):
        generator.generate("valid text for testing bounds", max_cards=0)
    with pytest.raises(GeneratorInputError):
        generator.generate("valid text for testing bounds", max_cards=21)
    assert called == 0


@pytest.mark.parametrize(
    "raw_body",
    [
        b"not json at all",
        b"[]",
        b"{}",
        json.dumps({"choices": []}).encode(),
        json.dumps({"choices": [{"message": {}}]}).encode(),
        json.dumps({"choices": [{"message": {"content": None}}]}).encode(),
        json.dumps({"choices": [{"message": {"content": "   "}}]}).encode(),
        _chat_completion_bytes("{broken json"),
        _chat_completion_bytes(["not", "an", "object"]),
        _chat_completion_bytes({}),
        _chat_completion_bytes({"cards": "not-a-list"}),
        _chat_completion_bytes({"cards": []}),
        _chat_completion_bytes(
            {
                "cards": [
                    {"front": f"Q{i}", "back": f"A{i}", "kind": "vocabulary"} for i in range(21)
                ]
            }
        ),
        _chat_completion_bytes({"cards": ["not-an-object"]}),
        _chat_completion_bytes(
            {"cards": [{"front": "   ", "back": "Answer", "kind": "vocabulary"}]}
        ),
        _chat_completion_bytes(
            {"cards": [{"front": "Question", "back": "", "kind": "vocabulary"}]}
        ),
        _chat_completion_bytes(
            {"cards": [{"front": "x" * 5001, "back": "Answer", "kind": "vocabulary"}]}
        ),
        _chat_completion_bytes(
            {"cards": [{"front": "Question", "back": "y" * 5001, "kind": "vocabulary"}]}
        ),
        _chat_completion_bytes(
            {"cards": [{"front": "Bad\x00text", "back": "Answer", "kind": "vocabulary"}]}
        ),
        _chat_completion_bytes({"cards": [{"front": 123, "back": "Answer", "kind": "vocabulary"}]}),
        _chat_completion_bytes(
            {"cards": [{"front": "Question", "back": "Answer", "kind": "cloze"}]}
        ),
        _chat_completion_bytes(
            {"cards": [{"front": "Question", "back": "Answer", "kind": "invalid_kind"}]}
        ),
        _chat_completion_bytes(
            {
                "cards": [
                    {"front": "Good", "back": "Card", "kind": "vocabulary"},
                    {"front": "Bad kind", "back": "Card", "kind": "unknown"},
                ]
            }
        ),
        b"x" * (MAX_RESPONSE_BYTES + 1),
    ],
)
def test_malformed_or_out_of_bounds_provider_output_raises_upstream_error(raw_body):
    opener, _ = _make_opener(raw_body)
    generator = OpenAICompatibleGenerator(
        api_key="sk-unit-secret",
        model="gpt-4o-mini",
        opener=opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=4)
    assert exc_info.value.status_code == 502


@pytest.mark.parametrize("status_code", [302, 401, 403, 404, 429, 500, 503])
def test_http_errors_map_to_502_without_leaking_secret(status_code):
    secret = "sk-never-leak-me-123456"

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            status_code,
            f"Upstream error echoing {secret}",
            hdrs=None,
            fp=io.BytesIO(f"Authorization: Bearer {secret}".encode()),
        )

    generator = OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=3)
    assert exc_info.value.status_code == 502
    assert str(status_code) in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: TimeoutError("read timed out"),
        lambda: urllib.error.URLError(TimeoutError("connect timed out")),
    ],
)
def test_timeouts_map_to_504(exc_factory):
    def opener(request, timeout):
        raise exc_factory()

    generator = OpenAICompatibleGenerator(
        api_key="sk-timeout-secret",
        model="gpt-4o-mini",
        timeout_seconds=7.5,
        opener=opener,
    )
    with pytest.raises(GeneratorTimeoutError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=3)
    assert exc_info.value.status_code == 504
    assert "7.5s" in str(exc_info.value)
    assert "sk-timeout-secret" not in str(exc_info.value)


def test_no_redirect_handler_blocks_redirects():
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _NoRedirectHandler().redirect_request(
            req, io.BytesIO(b""), 302, "Found", {}, "http://evil.example/v1"
        )
    assert exc_info.value.code == 302
    exc_info.value.close()


def test_network_error_maps_to_502_without_leaking_secret():
    secret = "sk-net-secret-999"

    def opener(request, timeout):
        raise urllib.error.URLError(f"connection failed for {secret}")

    generator = OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=3)
    assert exc_info.value.status_code == 502
    assert secret not in str(exc_info.value)


def test_api_generate_with_opt_in_adapter_persists_validated_cards(client, set_clock):
    set_clock(datetime(2026, 11, 24, 15, 0, 0, tzinfo=UTC))
    did = _create_deck(client)
    body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "  Explain PostgreSQL transactions.  ",
                    "back": "  Atomic units of work that commit or roll back together.  ",
                    "kind": "vocabulary",
                },
                {
                    "front": "Tell me about a time you fixed a broken migration.",
                    "back": "Use STAR to share a real migration issue you resolved.",
                    "kind": "behavioral",
                },
            ]
        }
    )
    opener, captured = _make_opener(body)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-api-test-secret",
        model="gpt-4o-mini",
        opener=opener,
    )

    response = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "PostgreSQL transactional migrations role", "max_cards": 5},
    )
    assert response.status_code == 201
    cards = response.json()
    assert len(cards) == 2
    assert cards[0]["front"] == "Explain PostgreSQL transactions."
    assert cards[0]["back"] == "Atomic units of work that commit or roll back together."
    assert cards[0]["kind"] == "vocabulary"
    assert cards[0]["due_date"] == "2026-11-24"
    assert cards[1]["kind"] == "behavioral"
    assert len(captured) == 1
    assert len(client.get("/cards", params={"deck_id": did}).json()) == 2


def test_api_generate_missing_deck_does_not_call_provider(client):
    called = 0

    def opener(request, timeout):
        nonlocal called
        called += 1
        return io.BytesIO(b"")

    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-api-test-secret",
        model="gpt-4o-mini",
        opener=opener,
    )

    response = client.post(
        "/cards/generate",
        json={"deck_id": 99999, "text": "PostgreSQL transactional migrations role"},
    )
    assert response.status_code == 404
    assert called == 0


def test_api_generate_errors_return_clean_json_and_persist_no_rows(client, monkeypatch):
    did = _create_deck(client)
    secret = "sk-api-never-leak-777"

    # 1. Misconfigured opt-in provider via real get_generator() -> 503, no fallback to mock.
    _clear_generator_env(monkeypatch)
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai_compatible")
    monkeypatch.setenv("GENERATOR_API_KEY", secret)
    monkeypatch.delenv("GENERATOR_MODEL", raising=False)
    get_settings.cache_clear()
    try:
        res_503 = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role"},
        )
        assert res_503.status_code == 503
        assert "GENERATOR_MODEL" in res_503.json()["detail"]
        assert secret not in res_503.text
    finally:
        _clear_generator_env(monkeypatch)

    # 2. Text exceeding configured generator_max_input_chars -> 422 before outbound request.
    called = 0

    def counting_opener(request, timeout):
        nonlocal called
        called += 1
        return io.BytesIO(b"")

    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        max_input_chars=25,
        opener=counting_opener,
    )
    res_422 = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "This input text is definitely longer than 25 chars"},
    )
    assert res_422.status_code == 422
    assert "25" in res_422.json()["detail"]
    assert called == 0

    # 3. Upstream timeout -> 504.
    def timeout_opener(request, timeout):
        raise TimeoutError(f"timed out with {secret}")

    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        timeout_seconds=5.0,
        opener=timeout_opener,
    )
    res_504 = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "AWS Python troubleshooting role"},
    )
    assert res_504.status_code == 504
    assert secret not in res_504.text

    # 4. Upstream HTTP 401 -> 502 without leaking secret.
    def auth_error_opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            f"Unauthorized {secret}",
            hdrs=None,
            fp=io.BytesIO(secret.encode()),
        )

    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=auth_error_opener,
    )
    res_502_http = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "AWS Python troubleshooting role"},
    )
    assert res_502_http.status_code == 502
    assert "401" in res_502_http.json()["detail"]
    assert secret not in res_502_http.text

    # 5. Partial-invalid structured output -> 502, zero rows persisted.
    partial_bad_body = _chat_completion_bytes(
        {
            "cards": [
                {"front": "Valid card", "back": "Valid answer", "kind": "vocabulary"},
                {"front": "   ", "back": "Broken card", "kind": "vocabulary"},
            ]
        }
    )
    opener, _ = _make_opener(partial_bad_body)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=opener,
    )
    res_502_bad = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "AWS Python troubleshooting role"},
    )
    assert res_502_bad.status_code == 502

    # 6. Custom provider returning empty list or invalid GeneratedCard -> 502, zero rows persisted.
    class EmptyProvider:
        def generate(self, text, max_cards):
            return []

    app.dependency_overrides[get_generator] = EmptyProvider
    assert (
        client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role"},
        ).status_code
        == 502
    )

    class InvalidCardProvider:
        def generate(self, text, max_cards):
            return [
                GeneratedCard("Valid", "Card", "vocabulary"),
                GeneratedCard("   ", "Blank front", "vocabulary"),
            ]

    app.dependency_overrides[get_generator] = InvalidCardProvider
    assert (
        client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role"},
        ).status_code
        == 502
    )

    # Confirm zero cards were persisted across every failed call.
    assert client.get("/cards", params={"deck_id": did}).json() == []


@pytest.mark.parametrize(
    ("url", "expect_proxy_disabled"),
    [
        ("http://127.0.0.1:11434/v1/chat/completions", True),
        ("http://localhost:8080/v1/chat/completions", True),
        ("http://LOCALHOST:8080/v1/chat/completions", True),
        ("https://api.openai.com/v1/chat/completions", False),
    ],
)
def test_default_urlopen_disables_proxies_for_loopback_http(
    monkeypatch, url, expect_proxy_disabled
):
    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")
    monkeypatch.delenv("no_proxy", raising=False)
    captured_handlers: list[tuple[object, ...]] = []

    class FakeOpener:
        def open(self, request, timeout):
            return io.BytesIO(b"{}")

    def fake_build_opener(*handlers):
        captured_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)

    req = urllib.request.Request(url, data=b"{}", method="POST")
    with _default_urlopen(req, timeout=5.0) as response:
        assert response.read() == b"{}"

    assert len(captured_handlers) == 1
    handlers = captured_handlers[0]
    assert any(isinstance(handler, _DeadlineHTTPHandler) for handler in handlers)
    assert any(isinstance(handler, _DeadlineHTTPSHandler) for handler in handlers)
    assert any(isinstance(handler, _NoRedirectHandler) for handler in handlers)
    proxy_handlers = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    if expect_proxy_disabled:
        assert len(proxy_handlers) == 1
        assert proxy_handlers[0].proxies == {}
    else:
        assert proxy_handlers == []


def test_chunked_read_enforces_end_to_end_deadline(client, monkeypatch):
    now = 100.0
    socket_timeouts: list[float] = []

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)

    class FakeSocket:
        def settimeout(self, value: float) -> None:
            socket_timeouts.append(value)

    class FakeRaw:
        _sock = FakeSocket()

    class FakeFP:
        raw = FakeRaw()

    class TrickleResponse:
        fp = FakeFP()

        def __init__(self) -> None:
            self._chunks = [b'{"choices":', b' [{"message":', b' {"content": "{}"}}]}']
            self._index = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            nonlocal now
            now += 0.4
            if self._index >= len(self._chunks):
                return b""
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk

    def opener(request, timeout):
        return TrickleResponse()

    generator = OpenAICompatibleGenerator(
        api_key="sk-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )

    with pytest.raises(GeneratorTimeoutError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 504
    assert "1s" in str(exc_info.value)
    assert len(socket_timeouts) == 3
    assert socket_timeouts[0] == pytest.approx(1.0)
    assert socket_timeouts[1] == pytest.approx(0.6)
    assert socket_timeouts[2] == pytest.approx(0.2)

    # Also verify HTTP 504 through the API endpoint with zero persisted rows.
    did = _create_deck(client)
    now = 200.0
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 504
    assert "sk-trickle-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_api_generate_malformed_bracketed_base_url_returns_503(client, monkeypatch):
    did = _create_deck(client)
    secret = "sk-bracket-url-secret"
    _clear_generator_env(monkeypatch)
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai_compatible")
    monkeypatch.setenv("GENERATOR_API_KEY", secret)
    monkeypatch.setenv("GENERATOR_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("GENERATOR_BASE_URL", "https://[invalid/v1")
    get_settings.cache_clear()
    try:
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role"},
        )
        assert res.status_code == 503
        assert "GENERATOR_BASE_URL" in res.json()["detail"]
        assert secret not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
    finally:
        _clear_generator_env(monkeypatch)


@pytest.mark.parametrize(
    "raw_body",
    [
        b"[" * 5000 + b"]" * 5000,
        _chat_completion_bytes("[" * 5000 + "]" * 5000),
    ],
)
def test_deeply_nested_json_raises_upstream_502(client, raw_body):
    assert len(raw_body) <= MAX_RESPONSE_BYTES
    opener, _ = _make_opener(raw_body)
    generator = OpenAICompatibleGenerator(
        api_key="sk-recursion-secret",
        model="gpt-4o-mini",
        opener=opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 502

    did = _create_deck(client)
    opener_api, _ = _make_opener(raw_body)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-recursion-secret",
        model="gpt-4o-mini",
        opener=opener_api,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 502
    assert "sk-recursion-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_header_trickle_within_http_response_begin_enforces_deadline(client, monkeypatch):
    now = 500.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)

    class TrickleHeaderSocket:
        def __init__(self, payload: bytes, chunk_size: int, step_seconds: float) -> None:
            self._payload = payload
            self._offset = 0
            self._chunk_size = chunk_size
            self._step_seconds = step_seconds
            self.timeouts: list[float] = []
            self.recv_calls = 0

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            nonlocal now
            self.recv_calls += 1
            now += self._step_seconds
            limit = nbytes if nbytes else len(buffer)
            size = min(self._chunk_size, limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"X-Header-1: value-one\r\n"
        b"X-Header-2: value-two\r\n"
        b"X-Header-3: value-three\r\n"
        b"Content-Length: 2\r\n"
        b"\r\n"
        b"{}"
    )
    created_sockets: list[TrickleHeaderSocket] = []

    def opener(request, timeout):
        raw_sock = TrickleHeaderSocket(raw_http, chunk_size=8, step_seconds=0.3)
        created_sockets.append(raw_sock)
        deadline_sock = _DeadlineSocket(raw_sock, fake_monotonic() + timeout)
        response = http.client.HTTPResponse(deadline_sock)
        response.begin()
        return response

    generator = OpenAICompatibleGenerator(
        api_key="sk-header-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )

    with pytest.raises(GeneratorTimeoutError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 504
    assert "1s" in str(exc_info.value)
    assert len(created_sockets) == 1
    sock = created_sockets[0]
    assert sock.recv_calls == 4
    assert sock.timeouts == pytest.approx([1.0, 0.7, 0.4, 0.1])

    did = _create_deck(client)
    now = 550.0
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-header-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 504
    assert "sk-header-trickle-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_buffered_body_trickle_within_single_read_enforces_deadline(client, monkeypatch):
    now = 600.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)

    class TrickleBodySocket:
        def __init__(self, headers: bytes, body: bytes) -> None:
            self._headers = headers
            self._headers_sent = False
            self._body = body
            self._body_offset = 0
            self.timeouts: list[float] = []
            self.body_recv_calls = 0

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            nonlocal now
            limit = nbytes if nbytes else len(buffer)
            if not self._headers_sent:
                size = min(limit, len(self._headers))
                buffer[:size] = self._headers[:size]
                self._headers = self._headers[size:]
                if not self._headers:
                    self._headers_sent = True
                return size
            self.body_recv_calls += 1
            now += 0.35
            size = min(64, limit, len(self._body) - self._body_offset)
            if size <= 0:
                return 0
            buffer[:size] = self._body[self._body_offset : self._body_offset + size]
            self._body_offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            import socket as _socket

            return io.BufferedReader(_socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    body = b"{" + b" " * 16382 + b"}"
    headers = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode()
    created_sockets: list[TrickleBodySocket] = []

    def opener(request, timeout):
        raw_sock = TrickleBodySocket(headers, body)
        created_sockets.append(raw_sock)
        response = http.client.HTTPResponse(raw_sock)
        response.begin()
        return response

    generator = OpenAICompatibleGenerator(
        api_key="sk-body-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )

    with pytest.raises(GeneratorTimeoutError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 504
    assert "1s" in str(exc_info.value)
    assert len(created_sockets) == 1
    sock = created_sockets[0]
    # BufferedReader.read(16384) loops internally over 64-byte recv_into calls;
    # the deadline fires on the 3rd internal recv_into (0.35 * 3 = 1.05s > 1.0s).
    assert sock.body_recv_calls == 3
    assert sock.timeouts[-3:] == pytest.approx([1.0, 0.65, 0.3])

    did = _create_deck(client)
    now = 650.0
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-body-trickle-secret",
        model="gpt-4o-mini",
        timeout_seconds=1.0,
        opener=opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 504
    assert "sk-body-trickle-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


@pytest.mark.parametrize(
    "raw_body",
    [
        b'{"big": ' + b"9" * 4500 + b"}",
        _chat_completion_bytes('{"cards": [], "big": ' + "9" * 4500 + "}"),
    ],
)
def test_oversized_integer_json_raises_upstream_502(client, raw_body):
    assert len(raw_body) <= MAX_RESPONSE_BYTES
    opener, _ = _make_opener(raw_body)
    generator = OpenAICompatibleGenerator(
        api_key="sk-bigint-secret",
        model="gpt-4o-mini",
        opener=opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 502

    did = _create_deck(client)
    opener_api, _ = _make_opener(raw_body)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-bigint-secret",
        model="gpt-4o-mini",
        opener=opener_api,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 502
    assert "sk-bigint-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_slow_dns_lookup_times_out_within_deadline_and_returns_504(client, monkeypatch):
    release_dns = threading.Event()
    secret = "sk-dns-timeout-secret"

    def slow_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        release_dns.wait(timeout=2.0)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]

    monkeypatch.setattr("app.generator.socket.getaddrinfo", slow_getaddrinfo)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        generator = OpenAICompatibleGenerator(
            api_key=secret,
            model="gpt-4o-mini",
            base_url="https://slow-dns.example.invalid/v1",
            timeout_seconds=0.05,
        )
        started = time.monotonic()
        with pytest.raises(GeneratorTimeoutError) as exc_info:
            generator.generate("Python backend API troubleshooting", max_cards=2)
        elapsed = time.monotonic() - started
        assert exc_info.value.status_code == 504
        assert elapsed < 0.5
        assert secret not in str(exc_info.value)

        did = _create_deck(client)
        app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
            api_key=secret,
            model="gpt-4o-mini",
            base_url="https://slow-dns.example.invalid/v1",
            timeout_seconds=0.05,
        )
        started_api = time.monotonic()
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "Python backend API troubleshooting"},
        )
        elapsed_api = time.monotonic() - started_api
        assert res.status_code == 504
        assert elapsed_api < 0.5
        assert secret not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
    finally:
        release_dns.set()


def test_https_connect_recomputes_budget_across_dns_tcp_and_tls(client, monkeypatch):
    now = 1000.0
    secret = "sk-tls-budget-secret"

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    dns_cost = 0.3
    tcp_cost = 0.4
    tls_cost = 0.4
    raw_sockets: list[object] = []
    tls_sockets: list[object] = []
    wrap_calls: list[tuple[object, str | None]] = []

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        nonlocal now
        now += dns_cost
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    class FakeRawSocket:
        def __init__(self, af, socktype, proto) -> None:
            self.timeouts: list[float] = []
            self.closed = False
            self.connected_to = None
            raw_sockets.append(self)

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def setsockopt(self, level: int, optname: int, value: int) -> None:
            pass

        def connect(self, address) -> None:
            nonlocal now
            self.connected_to = address
            now += tcp_cost

        def close(self) -> None:
            self.closed = True

    class FakeTLSSocket:
        def __init__(self) -> None:
            self.closed = False
            tls_sockets.append(self)

        def close(self) -> None:
            self.closed = True

    class FakeSSLContext:
        post_handshake_auth = None

        def set_alpn_protocols(self, protocols) -> None:
            pass

        def wrap_socket(self, sock, server_hostname=None):
            nonlocal now
            wrap_calls.append((sock, server_hostname))
            now += tls_cost
            return FakeTLSSocket()

    monkeypatch.setattr("app.generator.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.generator.socket.socket", FakeRawSocket)
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda: FakeSSLContext())

    # Sub-case 1: DNS (0.3s) + TCP (0.4s) leaves 0.3s for TLS; TLS takes 0.4s -> 504.
    conn = _DeadlineHTTPSConnection(
        "api.openai.com",
        443,
        context=FakeSSLContext(),
        deadline=now + 1.0,
    )
    with pytest.raises(TimeoutError):
        conn.connect()

    assert len(raw_sockets) == 1
    assert raw_sockets[0].timeouts == pytest.approx([0.7, 0.3])
    assert len(wrap_calls) == 1
    assert wrap_calls[0][1] == "api.openai.com"
    assert len(tls_sockets) == 1
    assert tls_sockets[0].closed is True

    # Verify full end-to-end API route maps TLS budget overrun to 504 with zero persisted rows.
    did = _create_deck(client)
    now = 1100.0
    raw_sockets.clear()
    tls_sockets.clear()
    wrap_calls.clear()
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=1.0,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 504
    assert secret not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []
    assert len(raw_sockets) == 1
    assert raw_sockets[0].timeouts == pytest.approx([0.7, 0.3])

    # Sub-case 2: DNS (0.4s) + TCP (0.65s) exhausts budget before wrap_socket is ever called.
    now = 1200.0
    dns_cost = 0.4
    tcp_cost = 0.65
    tls_cost = 0.1
    raw_sockets.clear()
    wrap_calls.clear()
    conn2 = _DeadlineHTTPSConnection(
        "api.openai.com",
        443,
        context=FakeSSLContext(),
        deadline=now + 1.0,
    )
    with pytest.raises(TimeoutError):
        conn2.connect()
    assert len(raw_sockets) == 1
    assert raw_sockets[0].closed is True
    assert wrap_calls == []


def test_http_and_https_proxy_tunnel_enforces_deadline_before_tunnel_io(monkeypatch):
    now = 1500.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)

    class SlowTunnelSocket:
        def __init__(self) -> None:
            self.timeouts: list[float] = []
            self.closed = False
            self.sent: list[bytes] = []

        def settimeout(self, value: float) -> None:
            self.timeouts.append(value)

        def sendall(self, data: bytes) -> None:
            nonlocal now
            self.sent.append(data)
            now += 0.6

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            nonlocal now
            now += 0.6
            payload = b"HTTP/1.1 200 Connection Established\r\n\r\n"
            buffer[: len(payload)] = payload
            return len(payload)

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    created: list[SlowTunnelSocket] = []

    def fake_connect_with_deadline(
        host, port, deadline, source_address=None, *, require_loopback=False
    ):
        sock = SlowTunnelSocket()
        created.append(sock)
        return sock

    monkeypatch.setattr("app.generator._connect_with_deadline", fake_connect_with_deadline)

    # Plaintext HTTP connections reject proxy tunnels before opening any socket.
    http_conn = _DeadlineHTTPConnection("proxy.local", 3128, deadline=now + 1.0)
    http_conn.set_tunnel("api.openai.com", 80)
    with pytest.raises(GeneratorConfigError) as http_exc:
        http_conn.connect()
    assert http_exc.value.status_code == 503
    assert created == []

    # HTTPS proxy tunnel times out before wrap_socket is called.
    now = 1600.0
    created.clear()
    wrap_called = False

    class NeverWrapContext:
        def wrap_socket(self, sock, server_hostname=None):
            nonlocal wrap_called
            wrap_called = True
            return sock

    https_conn = _DeadlineHTTPSConnection(
        "proxy.local", 3128, context=NeverWrapContext(), deadline=now + 1.0
    )
    https_conn.set_tunnel("api.openai.com", 443)
    with pytest.raises(TimeoutError):
        https_conn.connect()
    assert len(created) == 1
    assert created[0].timeouts == pytest.approx([1.0, 0.4])
    assert created[0].closed is True
    assert wrap_called is False


def test_connect_with_deadline_retries_multiple_addresses_with_shrinking_budget(monkeypatch):
    now = 2000.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("app.generator.time.monotonic", fake_monotonic)

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]

    attempts: list[tuple[tuple, float, bool]] = []

    class FakeSocket:
        def __init__(self, af, socktype, proto) -> None:
            self.af = af
            self.timeout = None
            self.closed = False

        def settimeout(self, value: float) -> None:
            self.timeout = value

        def connect(self, sa) -> None:
            nonlocal now
            if self.af == socket.AF_INET6:
                now += 0.3
                attempts.append((sa, self.timeout, False))
                raise ConnectionRefusedError("ipv6 refused")
            now += 0.1
            attempts.append((sa, self.timeout, True))

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("app.generator.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.generator.socket.socket", FakeSocket)

    sock = _connect_with_deadline("api.openai.com", 443, deadline=now + 1.0)
    assert sock.af == socket.AF_INET
    assert sock.closed is False
    assert len(attempts) == 2
    assert attempts[0][1] == pytest.approx(1.0)
    assert attempts[1][1] == pytest.approx(0.7)


def test_truncated_response_with_valid_json_prefix_returns_502_and_persists_no_cards(client):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain DNS resolution.",
                    "back": "Translating domain names into IP addresses.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    advertised_length = len(valid_body) + 50
    raw_http = (
        f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        f"Content-Length: {advertised_length}\r\n\r\n"
    ).encode() + valid_body

    class TruncatedSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def truncated_opener(request, timeout):
        response = http.client.HTTPResponse(TruncatedSocket(raw_http))
        response.begin()
        return response

    generator = OpenAICompatibleGenerator(
        api_key="sk-truncated-secret",
        model="gpt-4o-mini",
        opener=truncated_opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python DNS troubleshooting role", max_cards=2)
    assert exc_info.value.status_code == 502
    assert "incomplete" in str(exc_info.value).lower()

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-truncated-secret",
        model="gpt-4o-mini",
        opener=truncated_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python DNS troubleshooting role"},
    )
    assert res.status_code == 502
    assert "incomplete" in res.json()["detail"].lower()
    assert "sk-truncated-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_truncated_response_checked_against_content_length_even_when_length_attr_is_none():
    valid_body = _chat_completion_bytes(
        {"cards": [{"front": "Q", "back": "A", "kind": "vocabulary"}]}
    )

    class FakeHeaderOnlyResponse:
        headers = {"Content-Length": str(len(valid_body) + 25)}
        length = None

        def __init__(self) -> None:
            self._stream = io.BytesIO(valid_body)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            return self._stream.read(size)

    generator = OpenAICompatibleGenerator(
        api_key="sk-header-check-secret",
        model="gpt-4o-mini",
        opener=lambda req, timeout: FakeHeaderOnlyResponse(),
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 502
    assert "incomplete" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "content_length_headers",
    [
        ["-5"],
        ["not-a-number"],
        ["10, 20"],
        ["10", "20"],
        [str(MAX_RESPONSE_BYTES + 1)],
    ],
)
def test_invalid_or_oversized_content_length_fails_before_reading(content_length_headers):
    read_called = False

    class FakeMessage:
        def get_all(self, name: str):
            if name.lower() == "content-length":
                return content_length_headers
            return None

    class FakeResponse:
        headers = FakeMessage()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            nonlocal read_called
            read_called = True
            return b""

    generator = OpenAICompatibleGenerator(
        api_key="sk-cl-header-secret",
        model="gpt-4o-mini",
        opener=lambda req, timeout: FakeResponse(),
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 502
    assert read_called is False


def test_chunked_transfer_encoding_ignores_content_length_and_parses_cards():
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain HTTP chunked transfer encoding.",
                    "back": "Streams a body in length-prefixed chunks terminated by a zero chunk.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    chunk_frame = f"{len(valid_body):x}\r\n".encode() + valid_body + b"\r\n0\r\n\r\n"
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Content-Length: 999999999\r\n"
        b"\r\n" + chunk_frame
    )

    class ChunkedSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def chunked_opener(request, timeout):
        response = http.client.HTTPResponse(ChunkedSocket(raw_http))
        response.begin()
        return response

    generator = OpenAICompatibleGenerator(
        api_key="sk-chunked-secret",
        model="gpt-4o-mini",
        opener=chunked_opener,
    )
    cards = generator.generate("HTTP streaming troubleshooting", max_cards=2)
    assert len(cards) == 1
    assert cards[0].front == "Explain HTTP chunked transfer encoding."


@pytest.mark.parametrize(
    "bad_key",
    [
        "sk-snowman-\u2603",
        "sk-emoji-\U0001f511",
        "sk-latin1-caf\u00e9",
        "sk-with space",
        "sk-with\ttab",
        "sk-with\r\nX-Injected: 1",
    ],
)
def test_malformed_api_keys_return_503_without_leaking_key(client, monkeypatch, bad_key):
    with pytest.raises(GeneratorConfigError) as exc_info:
        OpenAICompatibleGenerator(api_key=bad_key, model="gpt-4o-mini")
    assert exc_info.value.status_code == 503
    assert bad_key not in str(exc_info.value)

    did = _create_deck(client)
    _clear_generator_env(monkeypatch)
    monkeypatch.setenv("GENERATOR_PROVIDER", "openai_compatible")
    monkeypatch.setenv("GENERATOR_API_KEY", bad_key)
    monkeypatch.setenv("GENERATOR_MODEL", "gpt-4o-mini")
    get_settings.cache_clear()
    try:
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "AWS Python troubleshooting role"},
        )
        assert res.status_code == 503
        assert "GENERATOR_API_KEY" in res.json()["detail"]
        assert bad_key not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
    finally:
        _clear_generator_env(monkeypatch)


def test_send_catches_unicode_encode_error_as_503(client):
    def unicode_fail_opener(request, timeout):
        raise UnicodeEncodeError("latin-1", "Bearer sk-\u2603", 10, 11, "ordinal not in range(256)")

    generator = OpenAICompatibleGenerator(
        api_key="sk-valid-ascii",
        model="gpt-4o-mini",
        opener=unicode_fail_opener,
    )
    with pytest.raises(GeneratorConfigError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 503
    assert "\u2603" not in str(exc_info.value)

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-valid-ascii",
        model="gpt-4o-mini",
        opener=unicode_fail_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 503
    assert "\u2603" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_stalled_dns_lookups_are_bounded_by_semaphore(client, monkeypatch):
    release_dns = threading.Event()
    started_lookups = 0
    started_lock = threading.Lock()
    spawned_threads = 0
    real_thread = threading.Thread

    def slow_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        nonlocal started_lookups
        with started_lock:
            started_lookups += 1
        release_dns.wait(timeout=2.0)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]

    def counting_thread(*args, **kwargs):
        nonlocal spawned_threads
        spawned_threads += 1
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(
        "app.generator._DNS_LOOKUP_SEMAPHORE",
        threading.BoundedSemaphore(MAX_CONCURRENT_DNS_LOOKUPS),
    )
    monkeypatch.setattr("app.generator.socket.getaddrinfo", slow_getaddrinfo)
    monkeypatch.setattr("app.generator.threading.Thread", counting_thread)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    try:
        generator = OpenAICompatibleGenerator(
            api_key="sk-dns-bound-secret",
            model="gpt-4o-mini",
            base_url="https://slow-dns.example.invalid/v1",
            timeout_seconds=0.03,
        )
        # Occupy all MAX_CONCURRENT_DNS_LOOKUPS slots with stalled lookups.
        for _ in range(MAX_CONCURRENT_DNS_LOOKUPS):
            with pytest.raises(GeneratorTimeoutError) as exc_info:
                generator.generate("Python backend API troubleshooting", max_cards=2)
            assert exc_info.value.status_code == 504

        assert spawned_threads == MAX_CONCURRENT_DNS_LOOKUPS

        # Additional requests must time out with 504 without spawning any new threads.
        for _ in range(3):
            with pytest.raises(GeneratorTimeoutError) as exc_info:
                generator.generate("Python backend API troubleshooting", max_cards=2)
            assert exc_info.value.status_code == 504

        did = _create_deck(client)
        app.dependency_overrides[get_generator] = lambda: generator
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "Python backend API troubleshooting"},
        )
        assert res.status_code == 504
        assert "sk-dns-bound-secret" not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
        assert spawned_threads == MAX_CONCURRENT_DNS_LOOKUPS
        assert started_lookups <= MAX_CONCURRENT_DNS_LOOKUPS
    finally:
        release_dns.set()


def test_huge_digit_content_length_returns_502_never_500(client):
    huge_length = "9" * 5000
    read_called = False

    class HugeLengthHeaders:
        def get_all(self, name: str):
            if name.lower() == "content-length":
                return [huge_length]
            return None

    class HugeLengthResponse:
        headers = HugeLengthHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            nonlocal read_called
            read_called = True
            return b""

    generator = OpenAICompatibleGenerator(
        api_key="sk-huge-cl-secret",
        model="gpt-4o-mini",
        opener=lambda req, timeout: HugeLengthResponse(),
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("Python backend API troubleshooting", max_cards=2)
    assert exc_info.value.status_code == 502
    assert read_called is False

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-huge-cl-secret",
        model="gpt-4o-mini",
        opener=lambda req, timeout: HugeLengthResponse(),
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python backend API troubleshooting"},
    )
    assert res.status_code == 502
    assert "Content-Length" in res.json()["detail"]
    assert "sk-huge-cl-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_generate_cards_releases_db_transaction_and_pool_connection_during_generation(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    active_sessions: list[Session] = []
    observed: dict[str, object] = {}

    def override_db():
        with Session(engine) as session:
            active_sessions.append(session)
            yield session

    class InspectingGenerator:
        def generate(self, text_input: str, max_cards: int) -> list[GeneratedCard]:
            route_session = active_sessions[-1]
            observed["in_transaction"] = route_session.in_transaction()
            observed["checkedout"] = engine.pool.checkedout()
            # With pool_size=1 and max_overflow=0, acquiring a connection here
            # proves the route returned its pooled connection before calling generate().
            with engine.connect() as conn:
                observed["probe"] = conn.execute(text("SELECT 1")).scalar_one()
            return [
                GeneratedCard(
                    front="What does releasing a DB transaction before I/O prevent?",
                    back="It prevents holding pooled DB connections during slow outbound calls.",
                    kind="vocabulary",
                )
            ]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_generator] = lambda: InspectingGenerator()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as pooled_client:
            did = _create_deck(pooled_client)
            res = pooled_client.post(
                "/cards/generate",
                json={"deck_id": did, "text": "Connection pool hygiene in FastAPI", "max_cards": 1},
            )
            assert res.status_code == 201
            assert len(res.json()) == 1
            assert observed == {
                "in_transaction": False,
                "checkedout": 0,
                "probe": 1,
            }
            assert engine.pool.checkedout() == 0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_generate_cards_returns_404_when_deck_deleted_during_generation(client, db_engine):
    did = _create_deck(client)

    class DeletingDeckGenerator:
        def generate(self, text_input: str, max_cards: int) -> list[GeneratedCard]:
            with Session(db_engine) as other_session:
                deck = other_session.get(Deck, did)
                assert deck is not None
                other_session.delete(deck)
                other_session.commit()
            return [
                GeneratedCard(
                    front="Explain foreign key integrity on concurrent delete.",
                    back="Deleting the parent deck must prevent orphaned cards.",
                    kind="vocabulary",
                )
            ]

    app.dependency_overrides[get_generator] = lambda: DeletingDeckGenerator()
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Concurrent deck deletion during generation", "max_cards": 1},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Deck not found"

    with Session(db_engine) as check_session:
        assert check_session.scalars(select(Card)).all() == []


def test_generate_cards_returns_404_when_deck_deleted_just_before_commit(client, db_engine):
    did = _create_deck(client)
    deleted_once = False

    def override_db_with_commit_race():
        with Session(db_engine) as session:

            @event.listens_for(session, "before_flush")
            def delete_deck_before_flush(_sess, _flush_context, _instances):
                nonlocal deleted_once
                if deleted_once:
                    return
                deleted_once = True
                with Session(db_engine) as other_session:
                    deck = other_session.get(Deck, did)
                    if deck is not None:
                        other_session.delete(deck)
                        other_session.commit()

            yield session

    class StaticGenerator:
        def generate(self, text_input: str, max_cards: int) -> list[GeneratedCard]:
            return [
                GeneratedCard(
                    front="Explain IntegrityError handling on commit.",
                    back="Roll back and map missing parent deck FK errors to 404.",
                    kind="vocabulary",
                )
            ]

    app.dependency_overrides[get_db] = override_db_with_commit_race
    app.dependency_overrides[get_generator] = lambda: StaticGenerator()
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Concurrent deck deletion before commit", "max_cards": 1},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Deck not found"

    with Session(db_engine) as check_session:
        assert check_session.scalars(select(Card)).all() == []


def test_concurrent_generation_burst_is_bounded_and_leaves_workers_free_for_other_endpoints(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.generator._GENERATION_SEMAPHORE",
        threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS),
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=QueuePool,
        pool_size=8,
        max_overflow=8,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)

    def override_db():
        with Session(engine) as session:
            yield session

    all_in_flight = threading.Event()
    release_generation = threading.Event()
    counter_lock = threading.Lock()
    in_flight = 0
    total_provider_calls = 0

    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain bounded concurrency in FastAPI.",
                    "back": "Capping slow outbound work keeps worker threads available.",
                    "kind": "vocabulary",
                }
            ]
        }
    )

    def blocking_opener(request: urllib.request.Request, timeout: float):
        nonlocal in_flight, total_provider_calls
        with counter_lock:
            in_flight += 1
            total_provider_calls += 1
            if in_flight == MAX_CONCURRENT_GENERATIONS:
                all_in_flight.set()
        try:
            assert release_generation.wait(timeout=10.0)
            return io.BytesIO(valid_body)
        finally:
            with counter_lock:
                in_flight -= 1

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-concurrency-test-secret",
        model="gpt-4o-mini",
        opener=blocking_opener,
    )
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as concurrent_client:
            did = _create_deck(concurrent_client)
            payload = {
                "deck_id": did,
                "text": "Bounded concurrency keeps FastAPI workers available",
                "max_cards": 1,
            }

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=MAX_CONCURRENT_GENERATIONS + 12
            ) as executor:
                in_flight_futures = [
                    executor.submit(concurrent_client.post, "/cards/generate", json=payload)
                    for _ in range(MAX_CONCURRENT_GENERATIONS)
                ]
                assert all_in_flight.wait(timeout=5.0), "initial generation requests never started"

                # While all MAX_CONCURRENT_GENERATIONS slots are blocked in flight,
                # a burst of extra generation calls must fail fast with 503.
                burst_futures = [
                    executor.submit(concurrent_client.post, "/cards/generate", json=payload)
                    for _ in range(6)
                ]
                burst_responses = [future.result(timeout=5.0) for future in burst_futures]
                assert all(res.status_code == 503 for res in burst_responses)
                assert all("concurrent" in res.json()["detail"].lower() for res in burst_responses)
                assert total_provider_calls == MAX_CONCURRENT_GENERATIONS

                # Unrelated endpoints must remain responsive while generation slots are full.
                other_futures = [
                    executor.submit(concurrent_client.get, "/decks"),
                    executor.submit(
                        concurrent_client.post,
                        "/decks",
                        json={"name": "Responsive While Generating"},
                    ),
                    executor.submit(concurrent_client.get, "/cards"),
                    executor.submit(concurrent_client.get, "/health"),
                ]
                other_responses = [future.result(timeout=5.0) for future in other_futures]
                assert [res.status_code for res in other_responses] == [200, 201, 200, 200]
                assert other_responses[3].json() == {"status": "ok"}

                # Release the slow provider and confirm all in-flight calls succeed.
                release_generation.set()
                in_flight_responses = [future.result(timeout=5.0) for future in in_flight_futures]
                assert [res.status_code for res in in_flight_responses] == [
                    201
                ] * MAX_CONCURRENT_GENERATIONS

            # Slots must be released so a subsequent generation request succeeds.
            follow_up = concurrent_client.post("/cards/generate", json=payload)
            assert follow_up.status_code == 201
            assert len(follow_up.json()) == 1
            assert total_provider_calls == MAX_CONCURRENT_GENERATIONS + 1
    finally:
        release_generation.set()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_direct_openai_compatible_generator_enforces_concurrency_limit(monkeypatch):
    monkeypatch.setattr(
        "app.generator._GENERATION_SEMAPHORE",
        threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS),
    )

    all_in_flight = threading.Event()
    release_generation = threading.Event()
    counter_lock = threading.Lock()
    started = 0

    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Why bound direct generator concurrency?",
                    "back": "It caps simultaneous outbound provider calls and releases slots.",
                    "kind": "vocabulary",
                }
            ]
        }
    )

    def blocking_opener(request: urllib.request.Request, timeout: float):
        nonlocal started
        with counter_lock:
            started += 1
            call_num = started
            if started == MAX_CONCURRENT_GENERATIONS:
                all_in_flight.set()
        assert release_generation.wait(timeout=10.0)
        if call_num == MAX_CONCURRENT_GENERATIONS:
            raise TimeoutError("simulated upstream timeout")
        return io.BytesIO(valid_body)

    generator = OpenAICompatibleGenerator(
        api_key="sk-direct-concurrency-secret",
        model="gpt-4o-mini",
        timeout_seconds=10.0,
        opener=blocking_opener,
    )

    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_GENERATIONS
        ) as executor:
            futures = [
                executor.submit(
                    generator.generate,
                    "Direct OpenAI-compatible concurrency test text",
                    1,
                )
                for _ in range(MAX_CONCURRENT_GENERATIONS)
            ]
            assert all_in_flight.wait(timeout=5.0)

            for _ in range(3):
                with pytest.raises(GeneratorBusyError) as exc_info:
                    generator.generate("Direct OpenAI-compatible concurrency test text", 1)
                assert exc_info.value.status_code == 503

            assert started == MAX_CONCURRENT_GENERATIONS

            release_generation.set()
            succeeded = 0
            timed_out = 0
            for future in futures:
                try:
                    cards = future.result(timeout=5.0)
                    assert len(cards) == 1
                    succeeded += 1
                except GeneratorTimeoutError:
                    timed_out += 1
            assert succeeded == MAX_CONCURRENT_GENERATIONS - 1
            assert timed_out == 1

        # Verify all slots (including the one that raised an exception) were released
        # by filling all MAX_CONCURRENT_GENERATIONS slots simultaneously again.
        barrier = threading.Barrier(MAX_CONCURRENT_GENERATIONS)

        def barrier_opener(request: urllib.request.Request, timeout: float):
            barrier.wait(timeout=5.0)
            return io.BytesIO(valid_body)

        follow_up_generator = OpenAICompatibleGenerator(
            api_key="sk-direct-concurrency-secret",
            model="gpt-4o-mini",
            timeout_seconds=10.0,
            opener=barrier_opener,
        )
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_GENERATIONS
        ) as executor:
            follow_up_futures = [
                executor.submit(
                    follow_up_generator.generate,
                    "Direct OpenAI-compatible concurrency test text",
                    1,
                )
                for _ in range(MAX_CONCURRENT_GENERATIONS)
            ]
            for future in follow_up_futures:
                cards = future.result(timeout=5.0)
                assert len(cards) == 1
    finally:
        release_generation.set()


@pytest.mark.parametrize(
    "resolved_infos",
    [
        [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.0.2.1", 8080),
            )
        ],
        [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 8080),
            ),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.0.2.1", 8080),
            ),
        ],
        [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("::1", 8080, 0, 0),
            ),
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::1", 8080, 0, 0),
            ),
        ],
    ],
)
def test_plaintext_http_localhost_rejects_non_loopback_resolved_ip_before_connect(
    client, monkeypatch, resolved_infos
):
    connect_called = False
    socket_created = False

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return resolved_infos

    class GuardSocket:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal socket_created
            socket_created = True

        def settimeout(self, value: float) -> None:
            pass

        def connect(self, sa) -> None:
            nonlocal connect_called
            connect_called = True
            raise AssertionError("socket.connect must not be called for non-loopback HTTP")

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.generator.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("app.generator.socket.socket", GuardSocket)

    generator = OpenAICompatibleGenerator(
        api_key="sk-loopback-guard-secret",
        model="gpt-4o-mini",
        base_url="http://localhost:8080/v1",
        timeout_seconds=1.0,
    )
    with pytest.raises(GeneratorConfigError) as exc_info:
        generator.generate("Python networking and DNS loopback safety", max_cards=2)
    assert exc_info.value.status_code == 503
    assert "loopback" in str(exc_info.value).lower()
    assert socket_created is False
    assert connect_called is False

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: generator
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "Python networking and DNS loopback safety"},
    )
    assert res.status_code == 503
    assert "loopback" in res.json()["detail"].lower()
    assert "sk-loopback-guard-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []
    assert socket_created is False
    assert connect_called is False


@pytest.mark.parametrize(
    "chunk_suffix",
    [
        b"0\r\n",
        b"0",
        b"0\r\nX-Trailer: 1\r\n",
        b"0\r\nX-Trailer: 1",
    ],
)
def test_truncated_chunked_response_without_final_blank_line_returns_502_and_persists_no_cards(
    client, chunk_suffix
):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain HTTP chunked framing termination.",
                    "back": "Chunked transfer ends with a zero chunk and a final CRLF.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    chunk_frame = f"{len(valid_body):x}\r\n".encode() + valid_body + b"\r\n" + chunk_suffix
    raw_http = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + chunk_frame

    class TruncatedChunkedSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def truncated_chunked_opener(request, timeout):
        response = http.client.HTTPResponse(TruncatedChunkedSocket(raw_http))
        response.begin()
        return response

    generator = OpenAICompatibleGenerator(
        api_key="sk-chunked-eof-secret",
        model="gpt-4o-mini",
        opener=truncated_chunked_opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("HTTP chunked transfer framing verification", max_cards=2)
    assert exc_info.value.status_code == 502
    assert "incomplete" in str(exc_info.value).lower()

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-chunked-eof-secret",
        model="gpt-4o-mini",
        opener=truncated_chunked_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "HTTP chunked transfer framing verification"},
    )
    assert res.status_code == 502
    assert "incomplete" in res.json()["detail"].lower()
    assert "sk-chunked-eof-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_truncated_chunked_response_over_real_loopback_http_returns_502(client):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "What terminates an HTTP/1.1 chunked body?",
                    "back": "A zero-length chunk followed by optional trailers and a blank line.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Connection: close\r\n"
        b"\r\n" + f"{len(valid_body):x}\r\n".encode() + valid_body + b"\r\n0\r\n"
    )

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(1)

    def serve_once() -> None:
        try:
            conn, _ = server_sock.accept()
            with conn:
                conn.settimeout(2.0)
                conn.recv(4096)
                conn.sendall(raw_http)
                conn.shutdown(socket.SHUT_WR)
                try:
                    while conn.recv(4096):
                        pass
                except OSError:
                    pass
        finally:
            server_sock.close()

    server_thread = threading.Thread(target=serve_once, daemon=True)
    server_thread.start()
    try:
        did = _create_deck(client)
        app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
            api_key="sk-live-chunked-eof-secret",
            model="gpt-4o-mini",
            base_url=f"http://127.0.0.1:{port}/v1",
            timeout_seconds=2.0,
        )
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "HTTP chunked transfer over loopback socket"},
        )
        assert res.status_code == 502
        assert "incomplete" in res.json()["detail"].lower()
        assert "sk-live-chunked-eof-secret" not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
    finally:
        server_thread.join(timeout=2.0)


def test_mock_generator_is_unaffected_by_hosted_concurrency_limit(tmp_path, monkeypatch):
    exhausted_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS)
    for _ in range(MAX_CONCURRENT_GENERATIONS):
        assert exhausted_semaphore.acquire(blocking=False)
    monkeypatch.setattr("app.generator._GENERATION_SEMAPHORE", exhausted_semaphore)

    engine = create_engine(
        f"sqlite:///{tmp_path / 'mock_concurrent.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=QueuePool,
        pool_size=8,
        max_overflow=8,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_generator] = lambda: MockGenerator()
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as mock_client:
            did = _create_deck(mock_client)
            payload = {
                "deck_id": did,
                "text": "AWS Python Docker PostgreSQL Linux monitoring",
                "max_cards": 2,
            }
            # Even with all hosted generation slots occupied, >MAX_CONCURRENT_GENERATIONS
            # concurrent MockGenerator requests must all succeed with 201.
            total_requests = MAX_CONCURRENT_GENERATIONS + 3
            with concurrent.futures.ThreadPoolExecutor(max_workers=total_requests) as executor:
                futures = [
                    executor.submit(mock_client.post, "/cards/generate", json=payload)
                    for _ in range(total_requests)
                ]
                responses = [future.result(timeout=5.0) for future in futures]
            assert [res.status_code for res in responses] == [201] * total_requests
            assert all(len(res.json()) == 2 for res in responses)
    finally:
        for _ in range(MAX_CONCURRENT_GENERATIONS):
            exhausted_semaphore.release()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize(
    "raw_transfer_encoding_headers",
    [
        b"Transfer-Encoding: gzip, chunked\r\n",
        b"Transfer-Encoding: chunked, identity\r\n",
        b"Transfer-Encoding: gzip\r\n",
        b"Transfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n",
    ],
)
def test_unsupported_or_combined_transfer_encoding_returns_502_without_persisting(
    client, raw_transfer_encoding_headers
):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain HTTP transfer-coding validation.",
                    "back": "Unsupported transfer-codings must fail closed before reading.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        + raw_transfer_encoding_headers
        + b"Content-Length: 999999\r\n"
        + b"\r\n"
        + valid_body
    )

    class RawResponseSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def bad_te_opener(request, timeout):
        response = http.client.HTTPResponse(RawResponseSocket(raw_http))
        response.begin()
        return response

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-bad-te-secret",
        model="gpt-4o-mini",
        opener=bad_te_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "HTTP Transfer-Encoding framing validation"},
    )
    assert res.status_code == 502
    assert "transfer-encoding" in res.json()["detail"].lower()
    assert "sk-bad-te-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


@pytest.mark.parametrize(
    "bad_chunk_size_line",
    [
        b"-5\r\n",
        b"+5\r\n",
        b"0x5\r\n",
        b"1_0\r\n",
        b"\r\n",
    ],
)
def test_signed_or_non_hex_chunk_size_returns_502_never_500(client, bad_chunk_size_line):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain RFC 9112 chunk-size grammar.",
                    "back": "Chunk size must be one or more unsigned hexadecimal digits.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n" + bad_chunk_size_line + valid_body + b"\r\n0\r\n\r\n"
    )

    class BadChunkSizeSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def bad_chunk_opener(request, timeout):
        response = http.client.HTTPResponse(BadChunkSizeSocket(raw_http))
        response.begin()
        return response

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key="sk-bad-chunk-size-secret",
        model="gpt-4o-mini",
        opener=bad_chunk_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "HTTP chunk-size hex validation"},
    )
    assert res.status_code == 502
    assert "sk-bad-chunk-size-secret" not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def _make_raw_http_socket_opener(raw_http: bytes):
    class RawHTTPResponseSocket:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
            self._offset = 0

        def settimeout(self, value: float) -> None:
            pass

        def recv_into(self, buffer, nbytes: int = 0) -> int:
            limit = nbytes if nbytes else len(buffer)
            size = min(limit, len(self._payload) - self._offset)
            if size <= 0:
                return 0
            buffer[:size] = self._payload[self._offset : self._offset + size]
            self._offset += size
            return size

        def makefile(self, mode: str = "rb", buffering: int | None = None):
            return io.BufferedReader(socket.SocketIO(self, "r"))

        def _decref_socketios(self) -> None:
            pass

        def close(self) -> None:
            pass

    def opener(request, timeout):
        response = http.client.HTTPResponse(RawHTTPResponseSocket(raw_http))
        response.begin()
        return response

    return opener


@pytest.mark.parametrize(
    ("chunk_delimiter", "trailing_frame"),
    [
        (b"XX", b"0\r\n\r\n"),
        (b"\n\n", b"0\r\n\r\n"),
        (b"\rX", b"0\r\n\r\n"),
        (b"X\n", b"0\r\n\r\n"),
        (b"\r", b""),
    ],
)
def test_chunked_non_crlf_data_delimiter_custom_opener_returns_502_and_persists_no_cards(
    client, chunk_delimiter, trailing_frame
):
    secret = "sk-chunk-delim-opener-secret"
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain HTTP/1.1 chunk-data framing.",
                    "back": "Every chunk-data block must be followed by an exact CRLF delimiter.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    chunk_frame = (
        f"{len(valid_body):x}\r\n".encode() + valid_body + chunk_delimiter + trailing_frame
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n" + chunk_frame
    )
    bad_delim_opener = _make_raw_http_socket_opener(raw_http)

    generator = OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=bad_delim_opener,
    )
    with pytest.raises(GeneratorUpstreamError) as exc_info:
        generator.generate("HTTP chunked delimiter verification", max_cards=2)
    assert exc_info.value.status_code == 502
    assert "incomplete" in str(exc_info.value).lower()
    assert secret not in str(exc_info.value)

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=bad_delim_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "HTTP chunked delimiter verification"},
    )
    assert res.status_code == 502
    assert "incomplete" in res.json()["detail"].lower()
    assert secret not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


@pytest.mark.parametrize(
    ("chunk_delimiter", "trailing_frame"),
    [
        (b"XX", b"0\r\n\r\n"),
        (b"\n\n", b"0\r\n\r\n"),
        (b"\rX", b"0\r\n\r\n"),
        (b"X\n", b"0\r\n\r\n"),
        (b"\r", b""),
    ],
)
def test_chunked_non_crlf_data_delimiter_over_real_loopback_http_returns_502_and_persists_no_cards(
    client, chunk_delimiter, trailing_frame
):
    secret = "sk-chunk-delim-live-secret"
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Why must chunk delimiters be validated strictly?",
                    "back": "Non-CRLF bytes after chunk data indicate malformed HTTP framing.",
                    "kind": "vocabulary",
                }
            ]
        }
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Connection: close\r\n"
        b"\r\n"
        + f"{len(valid_body):x}\r\n".encode()
        + valid_body
        + chunk_delimiter
        + trailing_frame
    )

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(1)

    def serve_once() -> None:
        try:
            conn, _ = server_sock.accept()
            with conn:
                conn.settimeout(2.0)
                conn.recv(4096)
                conn.sendall(raw_http)
                conn.shutdown(socket.SHUT_WR)
                try:
                    while conn.recv(4096):
                        pass
                except OSError:
                    pass
        finally:
            server_sock.close()

    server_thread = threading.Thread(target=serve_once, daemon=True)
    server_thread.start()
    try:
        did = _create_deck(client)
        app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
            api_key=secret,
            model="gpt-4o-mini",
            base_url=f"http://127.0.0.1:{port}/v1",
            timeout_seconds=2.0,
        )
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "HTTP chunked delimiter loopback socket test"},
        )
        assert res.status_code == 502
        assert "incomplete" in res.json()["detail"].lower()
        assert secret not in res.text
        assert client.get("/cards", params={"deck_id": did}).json() == []
    finally:
        server_thread.join(timeout=2.0)


@pytest.mark.parametrize(
    "build_chunked_body",
    [
        lambda body: f"{len(body):x}\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f" {len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f"{len(body):x} \r\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f"\t{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f"{len(body):x}\r\r\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f"{len(body):x};ext=a\rb\r\n".encode() + body + b"\r\n0\r\n\r\n",
        lambda body: f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\n",
        lambda body: f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\nX-Trailer: 1\n\r\n",
        lambda body: f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\nX-Trailer: 1\r2\r\n\r\n",
    ],
)
def test_chunked_strict_crlf_size_and_trailer_lines_return_502_and_persist_no_cards(
    client, build_chunked_body
):
    secret = "sk-strict-crlf-secret"
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "Explain CRLF requirements in HTTP/1.1 chunked encoding.",
                    "back": (
                        "Chunk-size and trailer lines must end with CRLF "
                        "without stray CR/LF or whitespace."
                    ),
                    "kind": "vocabulary",
                }
            ]
        }
    )
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n" + build_chunked_body(valid_body)
    )
    strict_opener = _make_raw_http_socket_opener(raw_http)

    did = _create_deck(client)
    app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
        api_key=secret,
        model="gpt-4o-mini",
        opener=strict_opener,
    )
    res = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "HTTP chunked CRLF validation"},
    )
    assert res.status_code == 502
    assert "incomplete" in res.json()["detail"].lower()
    assert secret not in res.text
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_valid_chunked_response_with_extension_and_trailer_over_real_loopback_http_returns_201(
    client,
):
    valid_body = _chat_completion_bytes(
        {
            "cards": [
                {
                    "front": "What constitutes a valid HTTP/1.1 chunked response?",
                    "back": (
                        "Hex chunk sizes with CRLF, CRLF after each chunk, "
                        "and a zero chunk ending with CRLF."
                    ),
                    "kind": "vocabulary",
                }
            ]
        }
    )
    split_at = len(valid_body) // 2
    part1, part2 = valid_body[:split_at], valid_body[split_at:]
    raw_http = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"Connection: close\r\n"
        b"\r\n"
        + f"{len(part1):x};ext=1\r\n".encode()
        + part1
        + b"\r\n"
        + f"{len(part2):X}\r\n".encode()
        + part2
        + b"\r\n0\r\nX-Trailer: ok\r\n\r\n"
    )

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]
    server_sock.listen(1)

    def serve_once() -> None:
        try:
            conn, _ = server_sock.accept()
            with conn:
                conn.settimeout(2.0)
                conn.recv(4096)
                conn.sendall(raw_http)
                conn.shutdown(socket.SHUT_WR)
                try:
                    while conn.recv(4096):
                        pass
                except OSError:
                    pass
        finally:
            server_sock.close()

    server_thread = threading.Thread(target=serve_once, daemon=True)
    server_thread.start()
    try:
        did = _create_deck(client)
        app.dependency_overrides[get_generator] = lambda: OpenAICompatibleGenerator(
            api_key="sk-valid-chunked-live-secret",
            model="gpt-4o-mini",
            base_url=f"http://127.0.0.1:{port}/v1",
            timeout_seconds=2.0,
        )
        res = client.post(
            "/cards/generate",
            json={"deck_id": did, "text": "Valid HTTP chunked framing over loopback socket"},
        )
        assert res.status_code == 201
        cards = res.json()
        assert len(cards) == 1
        assert cards[0]["front"] == "What constitutes a valid HTTP/1.1 chunked response?"
        assert len(client.get("/cards", params={"deck_id": did}).json()) == 1
    finally:
        server_thread.join(timeout=2.0)
