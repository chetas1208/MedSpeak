from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional

import httpx

from medspeak.config import Settings
from medspeak.schema import LanguageOption


class SmallestSTTError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class STTResult:
    transcription: str
    transcript: str
    raw_response: Dict[str, Any]


def _extract_transcription(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("transcription", "transcript", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            nested = _extract_transcription(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _extract_transcription(item)
            if nested:
                return nested
    return None


def _extract_utterances(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("utterances", "segments", "speaker_segments"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _coerce_seconds(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 600:
            return numeric / 1000.0
        return numeric
    return None


def _format_timestamp(seconds: Optional[float]) -> str:
    if seconds is None:
        return "00:00"
    total_seconds = max(0, int(round(seconds)))
    minutes, seconds_value = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_value:02d}"
    return f"{minutes:02d}:{seconds_value:02d}"


def format_diarized_transcript(utterances: List[Dict[str, Any]], fallback_text: str) -> str:
    lines: List[str] = []
    for item in utterances:
        text = str(item.get("text") or item.get("transcription") or "").strip()
        if not text:
            continue
        start = _coerce_seconds(item.get("start") or item.get("start_time"))
        end = _coerce_seconds(item.get("end") or item.get("end_time"))
        speaker = item.get("speaker", item.get("speaker_id", 0))
        speaker_label = speaker if isinstance(speaker, str) and speaker.startswith("SPEAKER_") else f"SPEAKER_{speaker}"
        lines.append(f"[{_format_timestamp(start)}-{_format_timestamp(end)}] {speaker_label}: {text}")
    return "\n".join(lines) if lines else fallback_text


def _is_transient_status(status_code: int, detail: str) -> bool:
    lowered = detail.lower()
    if status_code in {429, 500, 502, 503, 504}:
        return True
    return status_code == 403 and "temporarily unavailable" in lowered


def _failure_message(status_code: int, detail: str, *, transient: bool, exhausted: bool) -> str:
    detail_text = detail[:300]
    if transient and exhausted:
        return (
            "smallest.ai Pulse transcription failed after retrying a temporary provider issue "
            f"(status {status_code}): {detail_text}"
        )
    if status_code in {401, 403} and not transient:
        return (
            "smallest.ai Pulse transcription failed due to authentication or authorization "
            f"(status {status_code}): {detail_text}"
        )
    return f"smallest.ai Pulse transcription failed with status {status_code}: {detail_text}"


def transcribe_wav(
    *,
    wav_bytes: bytes,
    language: LanguageOption,
    settings: Settings,
    logger: Any,
) -> STTResult:
    settings.ensure_stt_ready()
    response: httpx.Response | None = None
    max_attempts = 3
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        for attempt in range(1, max_attempts + 1):
            response = client.post(
                "https://waves-api.smallest.ai/api/v1/pulse/get_text",
                params={
                    "model": "pulse",
                    "language": language,
                    "diarize": "true",
                    "word_timestamps": "true",
                },
                headers={
                    "Authorization": f"Bearer {settings.smallest_api_key}",
                    "Content-Type": "audio/wav",
                },
                content=wav_bytes,
            )
            if response.status_code < 400:
                break

            detail = response.text[:300]
            transient = _is_transient_status(response.status_code, detail)
            if transient and attempt < max_attempts:
                delay_seconds = float(attempt)
                logger.info(
                    "Retrying smallest.ai transcription after transient failure "
                    "(attempt %s/%s, status %s): %s",
                    attempt + 1,
                    max_attempts,
                    response.status_code,
                    detail,
                )
                time.sleep(delay_seconds)
                continue

            raise SmallestSTTError(
                _failure_message(
                    response.status_code,
                    detail,
                    transient=transient,
                    exhausted=transient and attempt == max_attempts,
                ),
                status_code=response.status_code,
            )

    if response is None:
        raise SmallestSTTError("smallest.ai Pulse transcription could not start.", status_code=502)

    try:
        payload = response.json()
    except ValueError as exc:
        raise SmallestSTTError("smallest.ai returned invalid JSON.") from exc

    transcription = _extract_transcription(payload)
    if not transcription:
        raise SmallestSTTError("smallest.ai did not return a transcription.")

    utterances = _extract_utterances(payload if isinstance(payload, dict) else {})
    transcript = format_diarized_transcript(utterances, transcription)
    logger.info("smallest.ai transcription complete")
    return STTResult(transcription=transcription, transcript=transcript, raw_response=payload)
