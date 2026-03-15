from __future__ import annotations

import re

from medspeak import schema


GENERIC_SPEAKER_PATTERN = re.compile(r"(?P<prefix>(?:\[[^\]]+\]\s*)?)(?P<label>SPEAKER_\d+)(?P<suffix>\s*:)", re.IGNORECASE)
DISPLAY_ALIASES = ("Patient", "Doctor")


def normalize_transcript_speakers(transcript: str) -> tuple[str, dict[str, str]]:
    if not transcript.strip():
        return transcript, {}

    speaker_map: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        label = match.group("label").upper()
        if label not in speaker_map:
            alias_index = len(speaker_map)
            speaker_map[label] = DISPLAY_ALIASES[alias_index] if alias_index < len(DISPLAY_ALIASES) else label
        return f"{match.group('prefix')}{speaker_map[label]}{match.group('suffix')}"

    normalized = GENERIC_SPEAKER_PATTERN.sub(replace, transcript)
    return normalized, speaker_map


def normalize_result_speakers(
    result: schema.AnalysisResult,
    speaker_map: dict[str, str],
) -> schema.AnalysisResult:
    if not speaker_map:
        return result

    normalized_timeline = [
        segment.model_copy(update={"speaker": speaker_map.get(segment.speaker.upper(), segment.speaker)})
        for segment in result.intent_timeline
    ]
    return result.model_copy(update={"intent_timeline": normalized_timeline})
