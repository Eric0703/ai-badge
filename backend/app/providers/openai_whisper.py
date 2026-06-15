"""OpenAI Whisper provider — placeholder until API key is configured.

Raises NotImplementedError until OPENAI_API_KEY is set to a real value.
Structure follows TranscriptionProvider interface for future activation.
"""

from typing import Optional
from app.config import settings
from app.providers.base import TranscriptionProvider, TranscriptResult


class OpenAIWhisperProvider(TranscriptionProvider):
    """OpenAI Whisper API transcription — NOT YET ACTIVE.

    Set OPENAI_API_KEY to a valid key to activate this provider.
    """

    def __init__(self, client: Optional[object] = None):
        """Initialize with optional pre-built OpenAI client (for testing)."""
        self.client = client

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptResult:
        """Transcribe audio — raises NotImplementedError until key is configured."""
        raise NotImplementedError("OPENAI_API_KEY not configured")
