from __future__ import annotations

import re
from typing import Any

from medspeak import nvidia_nim
from medspeak.config import Settings


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){2}\d{4}\b")
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+[A-Z0-9][A-Z0-9.\- ]+\s(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way)\b",
    re.IGNORECASE,
)


def _label_token(label: str) -> str:
    mapping = {
        "EMAIL": "[REDACTED_EMAIL]",
        "PHONE": "[REDACTED_PHONE]",
        "ADDRESS": "[REDACTED_ADDRESS]",
        "ID": "[REDACTED_ID]",
        "DOB": "[REDACTED_DOB]",
    }
    return mapping.get(label.upper(), "[REDACTED_PII]")


def redact_transcript(*, transcript: str, settings: Settings, logger: Any) -> str:
    if not settings.redact_pii:
        return transcript

    redacted = transcript
    try:
        entities = nvidia_nim.extract_pii_entities(settings=settings, transcript=transcript)
    except Exception as exc:
        logger.info(f"PII model fallback to regex only: {exc}")
        entities = []

    for entity in sorted(entities, key=lambda item: len(item["text"]), reverse=True):
        if str(entity.get("label", "")).upper() == "PERSON":
            continue
        redacted = redacted.replace(entity["text"], _label_token(entity["label"]))

    redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
    redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    redacted = ADDRESS_PATTERN.sub("[REDACTED_ADDRESS]", redacted)
    return redacted
