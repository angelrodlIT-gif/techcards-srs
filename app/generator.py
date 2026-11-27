"""Card generator seam: offline deterministic mock and opt-in OpenAI-compatible adapter."""

import contextlib
import errno
import http.client
import io
import ipaddress
import json
import math
import re
import socket
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
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
RESPONSE_READ_CHUNK_BYTES = 16_384
MAX_CONCURRENT_DNS_LOOKUPS = 8
MAX_CONCURRENT_GENERATIONS = 4
LOOPBACK_HTTP_HOSTS = frozenset({"127.0.0.1", "localhost"})
_DNS_LOOKUP_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_DNS_LOOKUPS)
_GENERATION_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS)
_GENERATION_SLOT_STATE = threading.local()

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


class GeneratorBusyError(GeneratorError):
    """Raised when the concurrent card generation limit is reached."""

    status_code = 503


@contextlib.contextmanager
def generation_slot() -> Iterator[None]:
    if getattr(_GENERATION_SLOT_STATE, "active", False):
        yield
        return
    semaphore = _GENERATION_SEMAPHORE
    if not semaphore.acquire(blocking=False):
        raise GeneratorBusyError(
            "Too many concurrent card generation requests in flight; try again shortly."
        )
    _GENERATION_SLOT_STATE.active = True
    try:
        yield
    finally:
        _GENERATION_SLOT_STATE.active = False
        semaphore.release()


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


def _is_printable_ascii_token(value: str) -> bool:
    return bool(value) and all(33 <= ord(ch) <= 126 for ch in value)


def validate_generator_base_url(raw_url: str) -> str:
    trimmed = raw_url.strip()
    if not trimmed:
        raise GeneratorConfigError("GENERATOR_BASE_URL must not be empty.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in trimmed):
        raise GeneratorConfigError(
            "GENERATOR_BASE_URL must not contain whitespace or control characters."
        )
    if not trimmed.isascii():
        raise GeneratorConfigError("GENERATOR_BASE_URL must contain only ASCII characters.")
    try:
        parsed = urlsplit(trimmed)
    except ValueError as exc:
        raise GeneratorConfigError("GENERATOR_BASE_URL must be a valid URL.") from exc
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http") or not parsed.hostname:
        raise GeneratorConfigError("GENERATOR_BASE_URL must be an absolute https:// URL.")
    if parsed.username is not None or parsed.password is not None:
        raise GeneratorConfigError("GENERATOR_BASE_URL must not include credentials.")
    if "?" in trimmed or "#" in trimmed or parsed.query or parsed.fragment:
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


def _is_loopback_http_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "http"
        and parsed.hostname is not None
        and parsed.hostname.lower() in LOOPBACK_HTTP_HOSTS
    )


def _resolve_with_deadline(host: str, port: int, deadline: float) -> list[tuple[Any, ...]]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("timed out")
    semaphore = _DNS_LOOKUP_SEMAPHORE
    if not semaphore.acquire(timeout=remaining):
        raise TimeoutError("timed out")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        semaphore.release()
        raise TimeoutError("timed out")

    result: list[tuple[Any, ...]] = []
    error: list[BaseException] = []

    def _lookup() -> None:
        try:
            result.extend(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM))
        except BaseException as exc:
            error.append(exc)
        finally:
            semaphore.release()

    thread = threading.Thread(target=_lookup, daemon=True)
    try:
        thread.start()
    except BaseException:
        semaphore.release()
        raise
    thread.join(timeout=remaining)
    if thread.is_alive() or time.monotonic() > deadline:
        raise TimeoutError("timed out")
    if error:
        raise error[0]
    if not result:
        raise OSError("getaddrinfo returns an empty list")
    return result


def _connect_with_deadline(
    host: str,
    port: int,
    deadline: float,
    source_address: Any = None,
    *,
    require_loopback: bool = False,
) -> socket.socket:
    infos = _resolve_with_deadline(host, port, deadline)
    if require_loopback:
        for _af, _socktype, _proto, _canonname, sa in infos:
            try:
                raw_ip = str(sa[0]).split("%", 1)[0]
                addr = ipaddress.ip_address(raw_ip)
            except (IndexError, TypeError, ValueError) as exc:
                raise GeneratorConfigError(
                    "Plaintext HTTP GENERATOR_BASE_URL must resolve exclusively "
                    "to loopback IP addresses."
                ) from exc
            if not addr.is_loopback:
                raise GeneratorConfigError(
                    "Plaintext HTTP GENERATOR_BASE_URL must resolve exclusively "
                    "to loopback IP addresses."
                )
    last_err: OSError | None = None
    for af, socktype, proto, _canonname, sa in infos:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out")
        sock: socket.socket | None = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.settimeout(remaining)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            if time.monotonic() > deadline:
                sock.close()
                raise TimeoutError("timed out")
            return sock
        except OSError as exc:
            last_err = exc
            if sock is not None:
                sock.close()
            if isinstance(exc, TimeoutError) or time.monotonic() >= deadline:
                raise TimeoutError("timed out") from exc
        except BaseException:
            if sock is not None:
                sock.close()
            raise
    if last_err is not None:
        raise last_err
    raise OSError("getaddrinfo returns an empty list")


def _set_tcp_nodelay(sock: Any) -> None:
    setsockopt = getattr(sock, "setsockopt", None)
    if not callable(setsockopt):
        return
    try:
        setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError as exc:
        if exc.errno != errno.ENOPROTOOPT:
            raise


class _DeadlineSocket:
    """Socket proxy that enforces an end-to-end monotonic deadline across every I/O call."""

    def __init__(self, sock: Any, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def _remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out")
        settimeout = getattr(self._sock, "settimeout", None)
        if callable(settimeout):
            settimeout(remaining)
        return remaining

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        self._remaining()
        data = self._sock.recv(bufsize) if flags == 0 else self._sock.recv(bufsize, flags)
        if time.monotonic() > self._deadline:
            raise TimeoutError("timed out")
        return data

    def recv_into(self, buffer: Any, nbytes: int = 0, flags: int = 0) -> int:
        self._remaining()
        if flags:
            count = self._sock.recv_into(buffer, nbytes, flags)
        elif nbytes:
            count = self._sock.recv_into(buffer, nbytes)
        else:
            count = self._sock.recv_into(buffer)
        if time.monotonic() > self._deadline:
            raise TimeoutError("timed out")
        return count

    def send(self, data: Any, flags: int = 0) -> int:
        self._remaining()
        sent = self._sock.send(data) if flags == 0 else self._sock.send(data, flags)
        if time.monotonic() > self._deadline:
            raise TimeoutError("timed out")
        return sent

    def sendall(self, data: Any, flags: int = 0) -> None:
        self._remaining()
        if flags == 0:
            self._sock.sendall(data)
        else:
            self._sock.sendall(data, flags)
        if time.monotonic() > self._deadline:
            raise TimeoutError("timed out")

    def makefile(
        self,
        mode: str = "r",
        buffering: int | None = None,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Any:
        if not set(mode) <= {"r", "w", "b"}:
            raise ValueError(f"invalid mode {mode!r} (only r, w, b allowed)")
        writing = "w" in mode
        reading = "r" in mode or not writing
        binary = "b" in mode
        rawmode = ("r" if reading else "") + ("w" if writing else "")
        raw = socket.SocketIO(self, rawmode)
        if hasattr(self._sock, "_io_refs"):
            self._sock._io_refs += 1
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            if not binary:
                raise ValueError("unbuffered streams must be binary")
            return raw
        if reading and writing:
            buffer: Any = io.BufferedRWPair(raw, raw, buffering)
        elif reading:
            buffer = io.BufferedReader(raw, buffering)
        else:
            buffer = io.BufferedWriter(raw, buffering)
        if binary:
            return buffer
        text = io.TextIOWrapper(buffer, io.text_encoding(encoding), errors, newline)
        text.mode = mode
        return text

    def _decref_socketios(self) -> None:
        decref = getattr(self._sock, "_decref_socketios", None)
        if callable(decref):
            decref()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)


class _StrictHTTPResponse(http.client.HTTPResponse):
    def _read_next_chunk_size(self) -> int:
        line = self.fp.readline(http.client._MAXLINE + 1)
        if len(line) > http.client._MAXLINE:
            raise http.client.LineTooLong("chunk size")
        if not line.endswith(b"\n"):
            self._close_conn()
            raise http.client.IncompleteRead(b"")
        i = line.find(b";")
        if i >= 0:
            line = line[:i]
        token = line.strip()
        if not token or not all(c in b"0123456789abcdefABCDEF" for c in token):
            self._close_conn()
            raise ValueError("invalid chunk size")
        try:
            return int(token, 16)
        except ValueError:
            self._close_conn()
            raise

    def _read_and_discard_trailer(self) -> None:
        trailers_read = 0
        while True:
            line = self.fp.readline(http.client._MAXLINE + 1)
            if len(line) > http.client._MAXLINE:
                raise http.client.LineTooLong("trailer line")
            if not line or not line.endswith(b"\n"):
                self._close_conn()
                raise http.client.IncompleteRead(b"")
            if line in (b"\r\n", b"\n"):
                break
            trailers_read += 1
            if trailers_read > http.client._MAXHEADERS:
                raise http.client.HTTPException(f"got more than {http.client._MAXHEADERS} trailers")


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    response_class = _StrictHTTPResponse

    def __init__(self, *args: Any, deadline: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._deadline = deadline

    def connect(self) -> None:
        if self._tunnel_host:
            raise GeneratorConfigError(
                "Plaintext HTTP GENERATOR_BASE_URL cannot use an HTTP proxy tunnel."
            )
        sys.audit("http.client.connect", self, self.host, self.port)
        raw_sock = _connect_with_deadline(
            self.host,
            self.port,
            self._deadline,
            self.source_address,
            require_loopback=True,
        )
        try:
            _set_tcp_nodelay(raw_sock)
        except BaseException:
            raw_sock.close()
            raise
        self.sock = _DeadlineSocket(raw_sock, self._deadline)


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    response_class = _StrictHTTPResponse

    def __init__(self, *args: Any, deadline: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._deadline = deadline

    def connect(self) -> None:
        sys.audit("http.client.connect", self, self.host, self.port)
        raw_sock = _connect_with_deadline(self.host, self.port, self._deadline, self.source_address)
        try:
            _set_tcp_nodelay(raw_sock)
        except BaseException:
            raw_sock.close()
            raise
        if self._tunnel_host:
            self.sock = _DeadlineSocket(raw_sock, self._deadline)
            try:
                self._tunnel()
            except BaseException:
                self.close()
                raise
            if time.monotonic() > self._deadline:
                self.close()
                raise TimeoutError("timed out")
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host

        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raw_sock.close()
            self.sock = None
            raise TimeoutError("timed out")
        try:
            raw_sock.settimeout(remaining)
            tls_sock = self._context.wrap_socket(raw_sock, server_hostname=server_hostname)
        except BaseException:
            raw_sock.close()
            self.sock = None
            raise
        if time.monotonic() > self._deadline:
            tls_sock.close()
            self.sock = None
            raise TimeoutError("timed out")
        self.sock = _DeadlineSocket(tls_sock, self._deadline)


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, deadline: float) -> None:
        super().__init__()
        self._deadline = deadline

    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_DeadlineHTTPConnection, req, deadline=self._deadline)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline: float) -> None:
        super().__init__()
        self._deadline = deadline

    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(
            _DeadlineHTTPSConnection,
            req,
            context=self._context,
            deadline=self._deadline,
        )


def _default_urlopen(
    request: urllib.request.Request,
    timeout: float,
    *,
    deadline: float | None = None,
) -> Any:
    effective_deadline = deadline if deadline is not None else (time.monotonic() + timeout)
    handlers: list[urllib.request.BaseHandler] = [
        _DeadlineHTTPHandler(effective_deadline),
        _DeadlineHTTPSHandler(effective_deadline),
        _NoRedirectHandler(),
    ]
    if _is_loopback_http_url(request.full_url):
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _ensure_response_deadline_socket(response: Any, deadline: float) -> None:
    if isinstance(response, http.client.HTTPResponse) and not isinstance(
        response, _StrictHTTPResponse
    ):
        response._read_next_chunk_size = types.MethodType(
            _StrictHTTPResponse._read_next_chunk_size, response
        )
        response._read_and_discard_trailer = types.MethodType(
            _StrictHTTPResponse._read_and_discard_trailer, response
        )
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None and not isinstance(sock, _DeadlineSocket):
        try:
            raw._sock = _DeadlineSocket(sock, deadline)
        except (AttributeError, TypeError):
            pass


def _set_response_socket_timeout(response: Any, timeout: float) -> None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    settimeout = getattr(sock, "settimeout", None)
    if callable(settimeout):
        settimeout(timeout)


def _header_values(headers: Any, name: str) -> list[str]:
    if headers is None:
        return []
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        raw = get_all(name)
        return [str(v) for v in raw] if raw else []
    if isinstance(headers, Mapping):
        target = name.lower()
        return [str(v) for k, v in headers.items() if str(k).lower() == target and v is not None]
    get = getattr(headers, "get", None)
    if callable(get):
        value = get(name)
        return [str(value)] if value is not None else []
    return []


def _is_chunked_transfer_encoding(response: Any, headers: Any) -> bool:
    chunked_flag = getattr(response, "chunked", None)
    raw_values = _header_values(headers, "transfer-encoding")
    if not raw_values:
        return chunked_flag is True
    normalized = [raw.strip().lower() for raw in raw_values]
    if normalized != ["chunked"] or chunked_flag is not True:
        raise GeneratorUpstreamError(
            "AI generator provider returned an unsupported Transfer-Encoding header."
        )
    return True


def _expected_content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(response, "msg", None)
    if headers is None or _is_chunked_transfer_encoding(response, headers):
        return None
    raw_values = _header_values(headers, "content-length")
    if not raw_values:
        return None
    parsed_lengths: set[int] = set()
    for raw in raw_values:
        for part in raw.split(","):
            token = part.strip()
            if not re.fullmatch(r"[0-9]+", token):
                raise GeneratorUpstreamError(
                    "AI generator provider returned an invalid Content-Length header."
                )
            try:
                parsed_lengths.add(int(token))
            except ValueError as exc:
                raise GeneratorUpstreamError(
                    "AI generator provider returned an invalid Content-Length header."
                ) from exc
    if len(parsed_lengths) != 1:
        raise GeneratorUpstreamError(
            "AI generator provider returned conflicting Content-Length headers."
        )
    expected = next(iter(parsed_lengths))
    if expected > MAX_RESPONSE_BYTES:
        raise GeneratorUpstreamError("AI generator provider response exceeded size limit.")
    return expected


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
        if not _is_printable_ascii_token(cleaned_key):
            raise GeneratorConfigError(
                "GENERATOR_API_KEY must be set to a valid printable ASCII token "
                "without whitespace or control characters when using "
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

    def _open_request(self, request: urllib.request.Request, deadline: float) -> Any:
        if self._opener is _default_urlopen:
            return _default_urlopen(request, self.timeout_seconds, deadline=deadline)
        return self._opener(request, self.timeout_seconds)

    def _read_response_with_deadline(self, response: Any, deadline: float) -> bytes:
        _ensure_response_deadline_socket(response, deadline)
        expected_content_length = _expected_content_length(response)
        chunks = bytearray()
        max_bytes = MAX_RESPONSE_BYTES + 1
        while len(chunks) < max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GeneratorTimeoutError(
                    f"AI generator provider timed out after {self.timeout_seconds:g}s."
                )
            _set_response_socket_timeout(response, remaining)
            to_read = min(RESPONSE_READ_CHUNK_BYTES, max_bytes - len(chunks))
            chunk = response.read(to_read)
            if not isinstance(chunk, bytes | bytearray):
                raise GeneratorUpstreamError(
                    "AI generator provider returned an invalid response body."
                )
            if time.monotonic() > deadline:
                raise GeneratorTimeoutError(
                    f"AI generator provider timed out after {self.timeout_seconds:g}s."
                )
            if not chunk:
                remaining_length = getattr(response, "length", None)
                if (
                    isinstance(remaining_length, int)
                    and not isinstance(remaining_length, bool)
                    and remaining_length > 0
                ):
                    raise GeneratorUpstreamError(
                        "AI generator provider returned an incomplete response."
                    )
                if expected_content_length is not None and len(chunks) < expected_content_length:
                    raise GeneratorUpstreamError(
                        "AI generator provider returned an incomplete response."
                    )
                break
            chunks.extend(chunk)
        return bytes(chunks)

    def _send(self, request: urllib.request.Request) -> bytes:
        with generation_slot():
            deadline = time.monotonic() + self.timeout_seconds
            try:
                with self._open_request(request, deadline) as response:
                    if time.monotonic() > deadline:
                        raise GeneratorTimeoutError(
                            f"AI generator provider timed out after {self.timeout_seconds:g}s."
                        )
                    raw_bytes = self._read_response_with_deadline(response, deadline)
            except UnicodeEncodeError as exc:
                raise GeneratorConfigError(
                    "GENERATOR_API_KEY or request headers contain unsupported characters."
                ) from exc
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
                raise GeneratorUpstreamError(
                    "AI generator provider network request failed."
                ) from exc
            except http.client.IncompleteRead as exc:
                raise GeneratorUpstreamError(
                    "AI generator provider returned an incomplete response."
                ) from exc
            except (http.client.HTTPException, OSError, ValueError) as exc:
                raise GeneratorUpstreamError(
                    "AI generator provider network request failed."
                ) from exc

        if not isinstance(raw_bytes, bytes | bytearray):
            raise GeneratorUpstreamError("AI generator provider returned an invalid response body.")
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            raise GeneratorUpstreamError("AI generator provider response exceeded size limit.")
        return bytes(raw_bytes)

    def _parse_response(self, raw_bytes: bytes, max_cards: int) -> list[GeneratedCard]:
        try:
            envelope = json.loads(raw_bytes.decode("utf-8"))
        except (ValueError, RecursionError) as exc:
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
        except (ValueError, RecursionError) as exc:
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


def _parse_generator_timeout_seconds(raw: Any) -> float:
    error_message = (
        f"GENERATOR_TIMEOUT_SECONDS must be > 0 and <= {MAX_GENERATOR_TIMEOUT_SECONDS:g}."
    )
    if isinstance(raw, bool):
        raise GeneratorConfigError(error_message)
    if isinstance(raw, int | float):
        value = float(raw)
    elif isinstance(raw, str):
        trimmed = raw.strip()
        if not trimmed:
            raise GeneratorConfigError(error_message)
        try:
            value = float(trimmed)
        except ValueError as exc:
            raise GeneratorConfigError(error_message) from exc
    else:
        raise GeneratorConfigError(error_message)
    if not math.isfinite(value) or not (0.0 < value <= MAX_GENERATOR_TIMEOUT_SECONDS):
        raise GeneratorConfigError(error_message)
    return value


def _parse_generator_max_input_chars(raw: Any) -> int:
    error_message = (
        f"GENERATOR_MAX_INPUT_CHARS must be between "
        f"{MIN_GENERATOR_INPUT_CHARS} and {MAX_GENERATOR_INPUT_CHARS}."
    )
    if isinstance(raw, bool):
        raise GeneratorConfigError(error_message)
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        trimmed = raw.strip()
        if not re.fullmatch(r"[+-]?[0-9]+", trimmed):
            raise GeneratorConfigError(error_message)
        try:
            value = int(trimmed)
        except ValueError as exc:
            raise GeneratorConfigError(error_message) from exc
    else:
        raise GeneratorConfigError(error_message)
    if not (MIN_GENERATOR_INPUT_CHARS <= value <= MAX_GENERATOR_INPUT_CHARS):
        raise GeneratorConfigError(error_message)
    return value


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
            timeout_seconds=_parse_generator_timeout_seconds(settings.generator_timeout_seconds),
            max_input_chars=_parse_generator_max_input_chars(settings.generator_max_input_chars),
        )

    raise GeneratorConfigError(f"Unsupported generator provider: {settings.generator_provider!r}.")
