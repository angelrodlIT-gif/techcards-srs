"""Card generator seam: offline deterministic mock and opt-in OpenAI-compatible adapter."""

import http.client
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import (
    DEFAULT_GENERATOR_BASE_URL,
    DEFAULT_GENERATOR_MAX_INPUT_CHARS,
    DEFAULT_GENERATOR_TIMEOUT_SECONDS,
    MAX_GENERATOR_INPUT_CHARS,
    MAX_GENERATOR_TIMEOUT_SECONDS,
    MIN_GENERATOR_INPUT_CHARS,
    get_settings,
)
from app.schemas import Kind, Text

GeneratedKind = Literal["vocabulary", "interview_phrase", "behavioral"]
Transport = Callable[[urllib.request.Request, float], Any]

MAX_GENERATED_CARDS = 20
MAX_RESPONSE_BYTES = 1_048_576
LOOPBACK_HTTP_HOSTS = frozenset({"127.0.0.1", "localhost"})

SYSTEM_PROMPT = (
    "You generate technical English flashcards for IT interview practice. "
    "Return ONLY a JSON object with a single key 'cards' containing a non-empty JSON array "
    "of card objects. Each card object must have 'front' (1-5000 characters), "
    "'back' (1-5000 characters), and 'kind' ('vocabulary', 'interview_phrase', or 'behavioral'). "
    "Never exceed the requested max_cards count. "
    "For 'interview_phrase' and 'behavioral' cards, write truthful practice or STAR prompts "
    "(Situation, Task, Action, Result) and never fabricate claims about the learner's "
    "experience or outcomes."
)


class GeneratorError(Exception):
    """Base error for card generator failures."""

    status_code: int = 502

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class GeneratorConfigError(GeneratorError):
    """Raised when the selected generator provider is missing or misconfigured."""

    status_code = 503


class GeneratorInputError(GeneratorError):
    """Raised when input text or bounds violate configured generator limits."""

    status_code = 422


class GeneratorTimeoutError(GeneratorError):
    """Raised when the upstream generator provider times out."""

    status_code = 504


class GeneratorUpstreamError(GeneratorError):
    """Raised when the upstream provider fails or returns invalid structured output."""

    status_code = 502


@dataclass(frozen=True)
class GeneratedCard:
    front: str
    back: str
    kind: Kind


class CardGenerator(Protocol):
    def generate(self, text: str, max_cards: int) -> list[GeneratedCard]: ...


class _GeneratedCardPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    front: Text
    back: Text
    kind: GeneratedKind


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def validate_generator_base_url(raw_url: str) -> str:
    trimmed = raw_url.strip()
    if not trimmed:
        raise GeneratorConfigError("GENERATOR_BASE_URL must not be empty.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in trimmed):
        raise GeneratorConfigError(
            "GENERATOR_BASE_URL must not contain whitespace or control characters."
        )
    parsed = urlsplit(trimmed)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http") or not parsed.hostname:
        raise GeneratorConfigError("GENERATOR_BASE_URL must be an absolute https:// URL.")
    if parsed.username is not None or parsed.password is not None:
        raise GeneratorConfigError("GENERATOR_BASE_URL must not include credentials.")
    if parsed.query or parsed.fragment:
        raise GeneratorConfigError("GENERATOR_BASE_URL must not include a query or fragment.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise GeneratorConfigError("GENERATOR_BASE_URL has an invalid port.") from exc
    if port is not None and not (1 <= port <= 65535):
        raise GeneratorConfigError("GENERATOR_BASE_URL has an invalid port.")
    if scheme == "http" and parsed.hostname.lower() not in LOOPBACK_HTTP_HOSTS:
        raise GeneratorConfigError(
            "GENERATOR_BASE_URL must use https:// "
            "(http:// is allowed only for localhost or 127.0.0.1)."
        )
    return trimmed.rstrip("/")


def build_chat_completions_url(base_url: str) -> str:
    normalized = validate_generator_base_url(base_url)
    if urlsplit(normalized).path.rstrip("/").endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _default_urlopen(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


GLOSSARY = {
    "aws": "Amazon Web Services: a cloud platform offering compute, storage and networking.",
    "python": "A programming language commonly used for APIs, automation and data processing.",
    "postgresql": "A relational database supporting SQL and transactions.",
    "docker": "A tool for packaging applications and dependencies in containers.",
    "linux": "An operating system commonly used to run cloud servers.",
    "terraform": "An infrastructure-as-code tool for declaring and provisioning resources.",
    "monitoring": "Observing system metrics, logs and events to detect problems.",
    "troubleshooting": "Investigating symptoms to identify and resolve a system problem.",
    "api": "Application programming interface: a contract for software communication.",
    "sql": "Structured Query Language: a language for querying relational databases.",
}


class MockGenerator:
    def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        terms = [term for term in GLOSSARY if term in words]
        cards = [
            GeneratedCard(f"Explain '{term}' in technical English.", GLOSSARY[term], "vocabulary")
            for term in terms
        ]
        # Templates are practice prompts, never claims about the learner's experience.
        topic = terms[0] if terms else "the technical responsibilities in this text"
        cards.extend(
            [
                GeneratedCard(
                    f"How would you discuss your experience with {topic}?",
                    f"Practice: I have worked with {topic} to [task]. "
                    "Use a truthful example and explain your contribution.",
                    "interview_phrase",
                ),
                GeneratedCard(
                    f"Tell me about a time you solved a problem involving {topic}.",
                    "Use STAR: describe the Situation, Task, Action and Result. "
                    "Choose a real experience; do not invent an outcome.",
                    "behavioral",
                ),
            ]
        )
        return cards[:max_cards]


class OpenAICompatibleGenerator:
    """Opt-in HTTP JSON chat-completions generator using Python stdlib urllib."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_GENERATOR_BASE_URL,
        timeout_seconds: float = DEFAULT_GENERATOR_TIMEOUT_SECONDS,
        max_input_chars: int = DEFAULT_GENERATOR_MAX_INPUT_CHARS,
        opener: Transport | None = None,
    ) -> None:
        cleaned_key = api_key.strip()
        if not cleaned_key or _has_control_chars(cleaned_key):
            raise GeneratorConfigError(
                "GENERATOR_API_KEY must be set to a valid token when using "
                "GENERATOR_PROVIDER=openai_compatible."
            )
        cleaned_model = model.strip()
        if not cleaned_model or _has_control_chars(cleaned_model):
            raise GeneratorConfigError(
                "GENERATOR_MODEL must be set when using GENERATOR_PROVIDER=openai_compatible."
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not math.isfinite(timeout_seconds)
            or not (0.0 < float(timeout_seconds) <= MAX_GENERATOR_TIMEOUT_SECONDS)
        ):
            raise GeneratorConfigError(
                f"GENERATOR_TIMEOUT_SECONDS must be > 0 and <= {MAX_GENERATOR_TIMEOUT_SECONDS:g}."
            )
        if (
            isinstance(max_input_chars, bool)
            or not isinstance(max_input_chars, int)
            or not (MIN_GENERATOR_INPUT_CHARS <= max_input_chars <= MAX_GENERATOR_INPUT_CHARS)
        ):
            raise GeneratorConfigError(
                f"GENERATOR_MAX_INPUT_CHARS must be between "
                f"{MIN_GENERATOR_INPUT_CHARS} and {MAX_GENERATOR_INPUT_CHARS}."
            )

        self._api_key = cleaned_key
        self.model = cleaned_model
        self.base_url = validate_generator_base_url(base_url)
        self.endpoint_url = build_chat_completions_url(self.base_url)
        self.timeout_seconds = float(timeout_seconds)
        self.max_input_chars = max_input_chars
        self._opener = opener or _default_urlopen

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleGenerator(model={self.model!r}, base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, max_input_chars={self.max_input_chars!r})"
        )

    def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
        if (
            isinstance(max_cards, bool)
            or not isinstance(max_cards, int)
            or not (1 <= max_cards <= MAX_GENERATED_CARDS)
        ):
            raise GeneratorInputError(f"max_cards must be between 1 and {MAX_GENERATED_CARDS}.")
        if "\x00" in text:
            raise GeneratorInputError("Input text must not contain NUL bytes.")
        cleaned_text = text.strip()
        if len(cleaned_text) < MIN_GENERATOR_INPUT_CHARS:
            raise GeneratorInputError(
                f"Input text must be at least {MIN_GENERATOR_INPUT_CHARS} characters."
            )
        if len(cleaned_text) > self.max_input_chars:
            raise GeneratorInputError(
                f"Input text exceeds configured generator_max_input_chars limit "
                f"({self.max_input_chars} characters)."
            )

        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Generate between 1 and {max_cards} flashcards from the following "
                            f"text.\n\nSource text:\n{cleaned_text}"
                        ),
                    },
                ],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        raw_bytes = self._send(request)
        return self._parse_response(raw_bytes, max_cards)

    def _send(self, request: urllib.request.Request) -> bytes:
        try:
            with self._opener(request, self.timeout_seconds) as response:
                raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403):
                raise GeneratorUpstreamError(
                    f"AI generator provider authentication failed (HTTP {code}). "
                    "Check GENERATOR_API_KEY."
                ) from exc
            if code == 404:
                raise GeneratorUpstreamError(
                    "AI generator provider endpoint or model was not found (HTTP 404). "
                    "Check GENERATOR_BASE_URL and GENERATOR_MODEL."
                ) from exc
            if code == 429:
                raise GeneratorUpstreamError(
                    "AI generator provider rate limit or quota exceeded (HTTP 429)."
                ) from exc
            if 300 <= code < 400:
                raise GeneratorUpstreamError(
                    f"AI generator provider returned a redirect (HTTP {code}), "
                    "which is not allowed."
                ) from exc
            raise GeneratorUpstreamError(
                f"AI generator provider request failed (HTTP {code})."
            ) from exc
        except TimeoutError as exc:
            raise GeneratorTimeoutError(
                f"AI generator provider timed out after {self.timeout_seconds:g}s."
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise GeneratorTimeoutError(
                    f"AI generator provider timed out after {self.timeout_seconds:g}s."
                ) from exc
            raise GeneratorUpstreamError("AI generator provider network request failed.") from exc
        except (http.client.HTTPException, OSError) as exc:
            raise GeneratorUpstreamError("AI generator provider network request failed.") from exc

        if not isinstance(raw_bytes, bytes | bytearray):
            raise GeneratorUpstreamError("AI generator provider returned an invalid response body.")
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            raise GeneratorUpstreamError("AI generator provider response exceeded size limit.")
        return bytes(raw_bytes)

    def _parse_response(self, raw_bytes: bytes, max_cards: int) -> list[GeneratedCard]:
        try:
            envelope = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GeneratorUpstreamError(
                "AI generator provider returned malformed JSON response."
            ) from exc

        if not isinstance(envelope, dict):
            raise GeneratorUpstreamError("AI generator provider response must be a JSON object.")
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise GeneratorUpstreamError("AI generator provider response is missing choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise GeneratorUpstreamError("AI generator provider response is missing message.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GeneratorUpstreamError("AI generator provider returned empty message content.")

        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise GeneratorUpstreamError(
                "AI generator provider content is not valid JSON."
            ) from exc

        if not isinstance(structured, dict):
            raise GeneratorUpstreamError(
                "AI generator provider JSON content must be an object with a 'cards' list."
            )
        raw_cards = structured.get("cards")
        if not isinstance(raw_cards, list):
            raise GeneratorUpstreamError("AI generator provider JSON is missing a 'cards' list.")
        if not raw_cards:
            raise GeneratorUpstreamError("AI generator provider returned an empty card list.")
        if len(raw_cards) > MAX_GENERATED_CARDS:
            raise GeneratorUpstreamError(
                f"AI generator provider returned {len(raw_cards)} cards, "
                f"exceeding maximum allowed ({MAX_GENERATED_CARDS})."
            )

        validated: list[GeneratedCard] = []
        for idx, item in enumerate(raw_cards):
            if not isinstance(item, dict):
                raise GeneratorUpstreamError(
                    f"AI generator provider card at index {idx} must be a JSON object."
                )
            try:
                parsed_card = _GeneratedCardPayload.model_validate(item)
            except ValidationError as exc:
                raise GeneratorUpstreamError(
                    f"AI generator provider returned an invalid card at index {idx}."
                ) from exc
            validated.append(
                GeneratedCard(
                    front=parsed_card.front,
                    back=parsed_card.back,
                    kind=parsed_card.kind,
                )
            )
        return validated[:max_cards]


def get_generator() -> CardGenerator:
    try:
        settings = get_settings()
    except ValidationError as exc:
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        suffix = f": {', '.join(fields)}" if fields else ""
        raise GeneratorConfigError(f"Invalid generator configuration{suffix}.") from exc

    if settings.generator_provider == "mock":
        return MockGenerator()

    if settings.generator_provider == "openai_compatible":
        api_key = (
            settings.generator_api_key.get_secret_value()
            if settings.generator_api_key is not None
            else ""
        )
        return OpenAICompatibleGenerator(
            api_key=api_key,
            model=settings.generator_model or "",
            base_url=settings.generator_base_url,
            timeout_seconds=settings.generator_timeout_seconds,
            max_input_chars=settings.generator_max_input_chars,
        )

    raise GeneratorConfigError(f"Unsupported generator provider: {settings.generator_provider!r}.")
