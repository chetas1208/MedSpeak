from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


NOT_STATED = "Not stated"
LanguageOption = Literal["en", "multi"]
CommunicationStyle = Literal["Direct", "Friendly", "Very explicit"]
IntentLabel = Literal[
    "SYMPTOMS",
    "MEDICAL_HISTORY",
    "MEDICATION_INSTRUCTION",
    "TEST_OR_LAB_ORDER",
    "REFERRAL",
    "FOLLOW_UP_PLAN",
    "RED_FLAGS_WARNING",
    "LIFESTYLE_GUIDANCE",
    "ADMIN_LOGISTICS",
    "CLARIFICATION_QUESTION",
    "OTHER",
]
JobStatus = Literal[
    "QUEUED",
    "NORMALIZE_AUDIO",
    "TRANSCRIBE",
    "REDACT",
    "ANALYZE",
    "VERIFY",
    "INDEX",
    "RENDER_PDF",
    "READY",
    "FAILED",
]


class Preferences(BaseModel):
    communication_style: CommunicationStyle = "Very explicit"
    sensory: List[str] = Field(default_factory=list)
    processing: List[str] = Field(default_factory=list)
    support: List[str] = Field(default_factory=list)


class AnalyzeFromAudioRequest(BaseModel):
    autism_mode: bool = True
    preferences: Preferences = Field(default_factory=Preferences)
    language: LanguageOption = "en"


class AnalyzeFromTranscriptRequest(AnalyzeFromAudioRequest):
    transcript: str = Field(min_length=1)

    @field_validator("transcript")
    @classmethod
    def _strip_transcript(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Transcript cannot be blank.")
        return cleaned


class IntentTimelineSegment(BaseModel):
    start: str
    end: str
    speaker: str
    text: str
    intents: List[str]
    confidence: float


class ChecklistItem(BaseModel):
    step: str
    who: str
    when: str


class MedicationItem(BaseModel):
    name: str
    dose: str
    frequency: str
    purpose: str
    notes: str


class TestReferralItem(BaseModel):
    item: str
    purpose: str
    when: str


class AccommodationCard(BaseModel):
    summary: str
    communication: List[str]
    sensory: List[str]
    processing: List[str]
    support: List[str]


class SocialScriptItem(BaseModel):
    situation: str
    script: str


class AnalysisResult(BaseModel):
    standard_summary: str
    autism_friendly_summary: str
    intent_summary: List[str]
    intent_timeline: List[IntentTimelineSegment]
    next_steps_checklist: List[ChecklistItem]
    medications: List[MedicationItem]
    tests_and_referrals: List[TestReferralItem]
    red_flags: List[str]
    questions_to_ask: List[str]
    accommodation_card: AccommodationCard
    social_scripts: List[SocialScriptItem]
    uncertainties: List[str]
    safety_note: str


class JobEnqueueResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    stage_times: Dict[str, str]
    error: Optional[str] = None
    transcript_redacted: Optional[str] = None
    result_json: Optional[AnalysisResult] = None
    pdf_path_or_url: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    ffmpeg_available: bool
    use_qdrant: bool
    worker_running: bool


def _normalize_string(value: Any) -> str:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or NOT_STATED
    return NOT_STATED


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        normalized = [_normalize_string(item) for item in value if isinstance(item, str) and item.strip()]
        return normalized or [NOT_STATED]
    if isinstance(value, str):
        return [_normalize_string(value)]
    return [NOT_STATED]


def _normalize_object_list(value: Any, fields: tuple[str, ...]) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        return [{field: NOT_STATED for field in fields}]
    normalized: List[Dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append({field: _normalize_string(item.get(field)) for field in fields})
        else:
            normalized.append({field: NOT_STATED for field in fields})
    return normalized


def normalize_analysis_payload(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    accommodation = data.get("accommodation_card") if isinstance(data.get("accommodation_card"), dict) else {}
    timeline = data.get("intent_timeline") if isinstance(data.get("intent_timeline"), list) else []

    normalized_timeline: List[Dict[str, Any]] = []
    if timeline:
        for segment in timeline:
            if isinstance(segment, dict):
                intents = segment.get("intents")
                normalized_intents = _normalize_string_list(intents)
                normalized_timeline.append(
                    {
                        "start": _normalize_string(segment.get("start")),
                        "end": _normalize_string(segment.get("end")),
                        "speaker": _normalize_string(segment.get("speaker")),
                        "text": _normalize_string(segment.get("text")),
                        "intents": normalized_intents if normalized_intents != [NOT_STATED] else ["OTHER"],
                        "confidence": float(segment.get("confidence", 0.0) or 0.0),
                    }
                )
    else:
        normalized_timeline.append(
            {
                "start": NOT_STATED,
                "end": NOT_STATED,
                "speaker": NOT_STATED,
                "text": NOT_STATED,
                "intents": ["OTHER"],
                "confidence": 0.0,
            }
        )

    return {
        "standard_summary": _normalize_string(data.get("standard_summary")),
        "autism_friendly_summary": _normalize_string(data.get("autism_friendly_summary")),
        "intent_summary": _normalize_string_list(data.get("intent_summary")),
        "intent_timeline": normalized_timeline,
        "next_steps_checklist": _normalize_object_list(data.get("next_steps_checklist"), ("step", "who", "when")),
        "medications": _normalize_object_list(
            data.get("medications"),
            ("name", "dose", "frequency", "purpose", "notes"),
        ),
        "tests_and_referrals": _normalize_object_list(
            data.get("tests_and_referrals"),
            ("item", "purpose", "when"),
        ),
        "red_flags": _normalize_string_list(data.get("red_flags")),
        "questions_to_ask": _normalize_string_list(data.get("questions_to_ask")),
        "accommodation_card": {
            "summary": _normalize_string(accommodation.get("summary")),
            "communication": _normalize_string_list(accommodation.get("communication")),
            "sensory": _normalize_string_list(accommodation.get("sensory")),
            "processing": _normalize_string_list(accommodation.get("processing")),
            "support": _normalize_string_list(accommodation.get("support")),
        },
        "social_scripts": _normalize_object_list(data.get("social_scripts"), ("situation", "script")),
        "uncertainties": _normalize_string_list(data.get("uncertainties")),
        "safety_note": _normalize_string(data.get("safety_note")),
    }
