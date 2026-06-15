"""Sensitive content checker — LLM-assisted detection (marks only, no decision)."""

import logging

from app.providers.base import LLMProvider
from app.providers.openai_llm import OpenAILLMProvider

logger = logging.getLogger("trust.sensitive")

SENSITIVE_PROMPT = """Analyze the following transcript for potentially sensitive information.

Return a JSON list of detected items. Each item should have:
- type: one of "pii" (personally identifiable), "financial", "credential", "medical", "confidential"
- excerpt: the exact text (max 80 chars)
- severity: "low", "medium", or "high"

Only flag items that are clearly sensitive. Do NOT flag normal business discussion.
If nothing sensitive is found, return an empty list.

Transcript:
---
{transcript}
---"""

SENSITIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["pii", "financial", "credential", "medical", "confidential"],
                    },
                    "excerpt": {"type": "string", "maxLength": 80},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["type", "excerpt", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

_llm: LLMProvider | None = None


def get_sensitive_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = OpenAILLMProvider()
    return _llm


def set_sensitive_llm(llm: LLMProvider) -> None:
    global _llm
    _llm = llm


async def check_sensitive(transcript: str) -> list[dict]:
    """Check a transcript for sensitive content using LLM.

    Returns a list of findings. The caller decides what action to take.
    This function only marks — it never blocks.
    """
    llm = get_sensitive_llm()
    prompt = SENSITIVE_PROMPT.format(transcript=transcript[:8000])  # Truncate
    try:
        result = await llm.complete(prompt, schema=SENSITIVE_SCHEMA, max_tokens=1024)
        findings = result.get("findings", [])
        logger.info(f"Sensitive check: {len(findings)} findings")
        return findings
    except Exception as e:
        logger.warning(f"Sensitive check failed: {e}")
        return []
