"""Speech-to-text service (P5-c, opt-in).

Flag: ``STOCKOS_VOICE_STT`` — ``off`` (default) or ``faster-whisper``.

``faster-whisper`` is an OPTIONAL dependency (lazy import, never imported at
module load). When the flag is on but the package is absent, callers get a
clean error telling them exactly what to install instead of an ImportError.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger("voice.stt")

INSTALL_HINT = "pip install faster-whisper (inside backend/.venv)"
DEFAULT_MODEL = "tiny"
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB cap per upload


@dataclass
class Transcription:
    text: str
    language: str | None
    duration_s: float | None
    model: str


class STTUnavailableError(RuntimeError):
    """Raised when STT is disabled or its optional backend is missing."""


def stt_backend() -> str:
    """Live env read (test-friendly, same pattern as the P5-a runtime flag)."""
    return (os.environ.get("STOCKOS_VOICE_STT") or "off").strip().lower()


def stt_model() -> str:
    return (os.environ.get("STOCKOS_VOICE_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _load_model(model_name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise STTUnavailableError(
            "faster-whisper is not installed. " + INSTALL_HINT
        ) from exc
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_file(path: str, *, model: str | None = None) -> Transcription:
    """Transcribe an audio file already on disk. Raises STTUnavailableError."""
    if stt_backend() != "faster-whisper":
        raise STTUnavailableError(
            "Voice STT is disabled. Set STOCKOS_VOICE_STT=faster-whisper to enable."
        )
    model_name = model or stt_model()
    whisper = _load_model(model_name)
    segments, info = whisper.transcribe(path, beam_size=5)
    text = "".join(s.text for s in segments).strip()
    language = getattr(info, "language", None)
    duration = getattr(info, "duration", None)
    return Transcription(text=text, language=language, duration_s=duration, model=model_name)


def transcribe_bytes(data: bytes, suffix: str, *, model: str | None = None) -> Transcription:
    """Transcribe raw upload bytes via a temp file (always cleaned up)."""
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError(f"Audio exceeds {MAX_AUDIO_BYTES // (1024 * 1024)} MB limit.")
    suffix = (suffix or "").lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported audio type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}")
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return transcribe_file(tmp_path, model=model)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:  # noqa: TRY203 - best-effort cleanup
                logger.warning("could not remove temp audio file")
