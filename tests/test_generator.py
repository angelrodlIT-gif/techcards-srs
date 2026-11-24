import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.generator import (
    MAX_RESPONSE_BYTES,
    GeneratedCard,
    GeneratorConfigError,
    GeneratorInputError,
    GeneratorTimeoutError,
    GeneratorUpstreamError,
    MockGenerator,
    OpenAICompatibleGenerator,
    _NoRedirectHandler,
    get_generator,
    validate_generator_base_url,
)
from app.main import app


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
            "generator_timeout_seconds",
        ),
        (
            {
                "GENERATOR_PROVIDER": "openai_compatible",
                "GENERATOR_API_KEY": "sk-test",
                "GENERATOR_MODEL": "gpt-4o-mini",
                "GENERATOR_MAX_INPUT_CHARS": "9",
            },
            "generator_max_input_chars",
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
        "https://api.openai.com:99999/v1",
        "https://api.openai.com:0/v1",
        "https://api.openai.com/v1\nX-Injected: 1",
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
