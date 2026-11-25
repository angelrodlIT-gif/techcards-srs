from collections import OrderedDict, deque
from contextlib import closing
from hashlib import sha256
from threading import Lock
from time import monotonic

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

MAX_AUDIO_BYTES = 512 * 1024
CACHE_ENTRIES = 64
CACHE_TTL_SECONDS = 24 * 3600
SYNTHESIS_ATTEMPTS_PER_HOUR = 20


class AudioUnavailable(Exception):
    pass


class SynthesisLimitReached(Exception):
    pass


def synthesize(text: str, region: str, voice_id: str) -> bytes:
    client = boto3.client(
        "polly",
        region_name=region,
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"total_max_attempts": 1},
            ignore_configured_endpoint_urls=True,
        ),
    )
    with closing(client):
        result = client.synthesize_speech(
            Text=text,
            TextType="text",
            Engine="standard",
            LanguageCode="en-US",
            VoiceId=voice_id,
            OutputFormat="mp3",
        )
        stream = result.get("AudioStream")
        if stream is None:
            raise AudioUnavailable
        with closing(stream):
            audio = stream.read(MAX_AUDIO_BYTES + 1)
        if result.get("ContentType") != "audio/mpeg" or not 1 <= len(audio) <= MAX_AUDIO_BYTES:
            raise AudioUnavailable
        return audio


class ListeningAudio:
    def __init__(self):
        self._lock = Lock()
        self._attempts: deque[float] = deque()
        self._cache: OrderedDict[tuple[str, str, bytes], tuple[float, bytes]] = OrderedDict()

    def get(self, text: str) -> bytes:
        settings = get_settings()
        region, voice = settings.polly_region.strip(), settings.polly_voice_id.strip()
        if not settings.polly_enabled or not region or not voice:
            raise AudioUnavailable
        key = (region, voice, sha256(text.encode()).digest())
        # Serialize cache misses so concurrent requests cannot duplicate a paid synthesis.
        if not self._lock.acquire(blocking=False):
            raise AudioUnavailable
        try:
            now = monotonic()
            for expired in [key for key, (expiry, _) in self._cache.items() if expiry <= now]:
                del self._cache[expired]
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key][1]
            while self._attempts and self._attempts[0] <= now - 3600:
                self._attempts.popleft()
            if len(self._attempts) >= SYNTHESIS_ATTEMPTS_PER_HOUR:
                raise SynthesisLimitReached
            self._attempts.append(now)
            try:
                audio = synthesize(text, region, voice)
            except (BotoCoreError, ClientError, OSError) as exc:
                raise AudioUnavailable from exc
            self._cache[key] = (monotonic() + CACHE_TTL_SECONDS, audio)
            if len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
            return audio
        finally:
            self._lock.release()


listening_audio = ListeningAudio()
