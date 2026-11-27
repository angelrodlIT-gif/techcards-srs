import re
from collections import OrderedDict
from threading import Lock, Timer

from fastapi import HTTPException

from app.models import Card
from app.schemas import PronunciationCompareInput, PronunciationCompareOut

MAX_BYTES = 512 * 1024
MAX_CLIPS = 32
TTL = 3600
MEDIA_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"}
RecordingKey = tuple[int, str | None]


class RecordingStore:
    def __init__(self):
        self._lock = Lock()
        self._clips: OrderedDict[RecordingKey, tuple[str, bytes, Timer]] = OrderedDict()

    def put(self, key: RecordingKey, media_type: str, audio: bytes):
        def expire():
            with self._lock:
                clip = self._clips.get(key)
                if clip is not None and clip[2] is timer:
                    self._clips.pop(key)

        timer = Timer(TTL, expire)
        timer.daemon = True
        with self._lock:
            self._delete(key)
            if len(self._clips) == MAX_CLIPS:
                _, (_, _, oldest) = self._clips.popitem(last=False)
                oldest.cancel()
            self._clips[key] = media_type, audio, timer
            timer.start()

    def get(self, key: RecordingKey) -> tuple[str, bytes] | None:
        with self._lock:
            clip = self._clips.get(key)
            if clip is None:
                return None
            self._clips.move_to_end(key)
            return clip[0], clip[1]

    def _delete(self, key: RecordingKey):
        clip = self._clips.pop(key, None)
        if clip is not None:
            clip[2].cancel()

    def delete(self, key: RecordingKey):
        with self._lock:
            self._delete(key)

    def clear(self):
        with self._lock:
            for _, _, timer in self._clips.values():
                timer.cancel()
            self._clips.clear()


recordings = RecordingStore()


def comparison(card: Card, payload: PronunciationCompareInput, has_recording: bool):
    if payload.microphone_available and not has_recording and not payload.spoken_transcript:
        raise HTTPException(409, "Record an attempt or provide a transcript to compare")
    reference = dict.fromkeys(re.findall(r"[\w']+", card.back.casefold()))
    spoken = dict.fromkeys(re.findall(r"[\w']+", (payload.spoken_transcript or "").casefold()))
    notes = ["Stress the words that carry meaning. Pause between clauses."]
    if card.explanation:
        notes.append(card.explanation)
    if payload.learner_notes:
        notes.append(payload.learner_notes)
    status = "microphone_denied_fallback"
    if payload.microphone_available:
        status = "recorded" if has_recording else "transcript_only"
    return PronunciationCompareOut(
        card_id=card.id,
        deck_id=card.deck_id,
        kind=card.kind,
        reference_text=card.back,
        card_explanation=card.explanation,
        has_recording=has_recording,
        recording_status=status,
        matched_terms=[word for word in reference if word in spoken],
        missing_terms=[word for word in reference if word not in spoken] if spoken else [],
        extra_terms=[word for word in spoken if word not in reference],
        intelligibility_focus="Listen for clear content words and natural phrase breaks.",
        pronunciation_notes=notes,
        workflow_steps=["Listen", "Shadow", "Record or repeat aloud", "Compare and self-grade"],
        evaluation_disclaimer="Term matching uses your transcript. Audio is for self-review.",
    )
