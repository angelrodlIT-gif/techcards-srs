import re
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic

from app.schemas import Kind, PronunciationCompareOut, RecordingStatus

PRONUNCIATION_KINDS = {
    "pronunciation",
    "vocabulary",
    "sentence",
    "interview_phrase",
    "listening",
}
MAX_RECORDING_BYTES = 512 * 1024
MAX_RECORDINGS = 32
RECORDING_TTL_SECONDS = 3600
ALLOWED_RECORDING_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
S_CLUSTER_RE = re.compile(r"\bs[tpkcmnl]\w*")
ED_ENDING_RE = re.compile(r"\b[a-z]{2,}ed\b")

LETTER_ACRONYMS = {
    "IP",
    "DNS",
    "VPC",
    "TCP",
    "UDP",
    "HTTP",
    "HTTPS",
    "SSH",
    "TLS",
    "IAM",
    "AWS",
    "NAT",
    "BGP",
    "API",
    "URL",
    "TTL",
    "CPU",
    "RAM",
    "CDN",
    "VPN",
    "ACL",
    "SLA",
    "SLO",
    "SRE",
    "JWT",
    "SSL",
    "DHCP",
    "ARP",
    "MTU",
    "ICMP",
}
NON_ED_SUFFIX_WORDS = {
    "need",
    "feed",
    "seed",
    "speed",
    "bleed",
    "indeed",
    "exceed",
    "proceed",
    "succeed",
    "hundred",
}
VOICED_VZ_WORDS = {
    "server",
    "servers",
    "service",
    "services",
    "resolve",
    "resolves",
    "resolved",
    "resolver",
    "resolvers",
    "available",
    "availability",
    "virtual",
    "private",
    "version",
    "versions",
    "over",
    "caches",
    "expires",
    "expired",
    "zero",
    "zone",
    "zones",
    "failover",
    "verify",
    "valid",
    "value",
    "values",
    "event",
    "events",
    "device",
    "devices",
    "ipv4",
    "ipv6",
}

RHYTHM_NOTE = (
    "Stress content words and pause cleanly at clause boundaries while keeping "
    "final consonants audible."
)
PACE_NOTE = (
    "Shadow at a steady pace rather than rushing; clear word boundaries improve "
    "listener intelligibility more than speed."
)
EVALUATION_DISCLAIMER = (
    "Feedback focuses on listener intelligibility and actionable pronunciation habits. "
    "No numeric scores, percentages, phoneme grades, or CEFR levels are computed."
)


class PronunciationRecordingStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._recordings: OrderedDict[int, tuple[float, int, bytes, str, bytes]] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        for cid in [k for k, (expiry, *_) in self._recordings.items() if expiry <= now]:
            del self._recordings[cid]

    def put(
        self, card_id: int, deck_id: int, reference_text: str, media_type: str, audio: bytes
    ) -> None:
        digest = sha256(reference_text.encode()).digest()
        with self._lock:
            now = monotonic()
            self._purge_expired(now)
            self._recordings[card_id] = (
                now + RECORDING_TTL_SECONDS,
                deck_id,
                digest,
                media_type,
                audio,
            )
            self._recordings.move_to_end(card_id)
            while len(self._recordings) > MAX_RECORDINGS:
                self._recordings.popitem(last=False)

    def get(self, card_id: int, deck_id: int, reference_text: str) -> tuple[str, bytes] | None:
        digest = sha256(reference_text.encode()).digest()
        with self._lock:
            self._purge_expired(monotonic())
            entry = self._recordings.get(card_id)
            if entry is None:
                return None
            _, stored_deck_id, stored_digest, media_type, audio = entry
            if stored_deck_id != deck_id or stored_digest != digest:
                del self._recordings[card_id]
                return None
            self._recordings.move_to_end(card_id)
            return media_type, audio

    def delete(self, card_id: int) -> None:
        with self._lock:
            self._purge_expired(monotonic())
            self._recordings.pop(card_id, None)

    def delete_deck(self, deck_id: int) -> None:
        with self._lock:
            self._purge_expired(monotonic())
            for cid in [k for k, (_, d_id, *_) in self._recordings.items() if d_id == deck_id]:
                del self._recordings[cid]

    def clear(self) -> None:
        with self._lock:
            self._recordings.clear()


pronunciation_recordings = PronunciationRecordingStore()


def _unique_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(TOKEN_RE.findall(text.lower())))


def _build_notes(
    reference_text: str,
    ref_tokens: list[str],
    card_explanation: str | None,
    learner_notes: str | None,
) -> list[str]:
    notes: list[str] = []
    acronyms = list(dict.fromkeys(ACRONYM_RE.findall(reference_text)))
    if "CIDR" in acronyms:
        notes.append("Pronounce 'CIDR' as 'cider' (/ˈsaɪdər/).")
    if "SQL" in acronyms:
        notes.append("Pronounce 'SQL' as 'sequel' or letter-by-letter S-Q-L with stress on L.")
    spelled = [tok for tok in acronyms if tok in LETTER_ACRONYMS]
    if spelled:
        notes.append(
            f"Spell out acronyms like {'/'.join(spelled[:4])} clearly with primary stress "
            "on the final letter."
        )

    lower = reference_text.lower()
    s_clusters = list(dict.fromkeys(S_CLUSTER_RE.findall(lower)))
    if s_clusters:
        examples = ", ".join(f"'{w}'" for w in s_clusters[:3])
        notes.append(
            f"Start initial s-clusters directly on /s/ without adding an initial /e/ vowel "
            f"before {examples}."
        )

    ed_words = [
        w for w in dict.fromkeys(ED_ENDING_RE.findall(lower)) if w not in NON_ED_SUFFIX_WORDS
    ]
    if ed_words:
        examples = ", ".join(f"'{w}'" for w in ed_words[:3])
        notes.append(
            f"Pronounce regular -ed endings ({examples}) as /t/ or /d/ without adding an "
            "extra syllable unless the stem ends in /t/ or /d/."
        )

    vz_words = [w for w in ref_tokens if w in VOICED_VZ_WORDS]
    if vz_words:
        examples = ", ".join(f"'{w}'" for w in vz_words[:3])
        notes.append(
            f"Keep voiced /v/ (teeth on lower lip) and /z/ distinct in technical terms "
            f"like {examples}."
        )

    if card_explanation:
        notes.append(f"Card note: {card_explanation}")
    if len(notes) < 2:
        notes.append(RHYTHM_NOTE)
    if len(notes) < 2:
        notes.append(PACE_NOTE)
    if learner_notes:
        notes.append(f"Self-check note: {learner_notes}")
    return notes


def build_pronunciation_comparison(
    *,
    card_id: int,
    deck_id: int,
    kind: Kind,
    reference_text: str,
    card_explanation: str | None,
    has_recording: bool,
    recording_status: RecordingStatus,
    spoken_transcript: str | None = None,
    learner_notes: str | None = None,
) -> PronunciationCompareOut:
    ref_tokens = _unique_tokens(reference_text)
    if spoken_transcript is not None:
        spoken_tokens = _unique_tokens(spoken_transcript)
        spoken_set, ref_set = set(spoken_tokens), set(ref_tokens)
        matched_terms = [t for t in ref_tokens if t in spoken_set]
        missing_terms = [t for t in ref_tokens if t not in spoken_set]
        extra_terms = [t for t in spoken_tokens if t not in ref_set]
        if not missing_terms and not extra_terms:
            focus = (
                "All key reference terms were captured. Re-shadow once more focusing on "
                "content-word stress and clear final consonants."
            )
        else:
            parts: list[str] = []
            if missing_terms:
                parts.append(f"articulate missing terms ({', '.join(missing_terms[:5])})")
            if extra_terms:
                parts.append(f"trim extra terms ({', '.join(extra_terms[:5])})")
            focus = f"Re-shadow for listener intelligibility: {' and '.join(parts)}."
    else:
        matched_terms, missing_terms, extra_terms = [], [], []
        if recording_status == "microphone_denied_fallback":
            focus = (
                "Microphone fallback active: shadow the reference aloud and compare your "
                "rhythm, content-word stress, and final consonants against the notes."
            )
        else:
            focus = (
                "Replay your local recording alongside the reference, comparing rhythm, "
                "content-word stress, and final consonants."
            )

    step_three = (
        "3. Microphone-denied fallback: Practice aloud without recording, optionally "
        "submitting a spoken transcript or self-check note."
        if recording_status == "microphone_denied_fallback"
        else "3. Record: Capture an opt-in local recording in memory and replay it back."
    )
    workflow_steps = [
        "1. Listen: Play the reference audio (or read the reference text if offline).",
        "2. Shadow: Repeat the phrase aloud in real time, matching stress and pauses.",
        step_three,
        "4. Compare: Review the intelligibility focus and notes, delete your clip when "
        "done, and self-grade with SM-2.",
    ]

    return PronunciationCompareOut(
        card_id=card_id,
        deck_id=deck_id,
        kind=kind,
        reference_text=reference_text,
        card_explanation=card_explanation,
        has_recording=has_recording,
        recording_status=recording_status,
        matched_terms=matched_terms,
        missing_terms=missing_terms,
        extra_terms=extra_terms,
        intelligibility_focus=focus,
        pronunciation_notes=_build_notes(
            reference_text, ref_tokens, card_explanation, learner_notes
        ),
        workflow_steps=workflow_steps,
        evaluation_disclaimer=EVALUATION_DISCLAIMER,
    )
