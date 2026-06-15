"""Capture service — Whisper transcription via provider.

Default provider is Mock (no API key needed). Switch to OpenAIWhisperProvider
when OPENAI_API_KEY is configured.
"""

import logging
import os

from app.config import settings
from app.providers.base import TranscriptionProvider, TranscriptResult
from app.providers.mock_whisper import MockWhisperProvider

logger = logging.getLogger("capture")

_transcriber: TranscriptionProvider | None = None


def get_transcriber() -> TranscriptionProvider:
    global _transcriber
    if _transcriber is None:
        _transcriber = MockWhisperProvider()
    return _transcriber


def set_transcriber(t: TranscriptionProvider) -> None:
    """Override the transcriber (for testing or when switching to real Whisper)."""
    global _transcriber
    _transcriber = t


async def transcribe_audio(audio_key: str, language: str | None = None) -> TranscriptResult:
    """Transcribe an audio file by key."""
    file_path = os.path.join(settings.audio_storage_path, audio_key)
    logger.info(f"Transcribing {file_path}")
    transcriber = get_transcriber()
    result = await transcriber.transcribe(file_path, language=language)
    logger.info(f"Transcription complete: {len(result.transcript)} chars, {len(result.segments)} segments")
    return result
