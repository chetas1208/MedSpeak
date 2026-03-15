from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


UnsupportedAnswer = "I can’t verify that from your visit record."
SourceType = Literal["current_transcript", "current_result", "prior_visit", "site_context"]
ChatRole = Literal["user", "assistant"]
ChatMessageStatus = Literal["draft", "refining", "final", "failed"]


class RetrievedSource(BaseModel):
    source_type: SourceType
    visit_id: str
    chunk_id: str
    text: str
    score: float = 0.0


class UsedSource(BaseModel):
    source_type: SourceType
    chunk_id: str
    visit_id: str
    quote: str


class ChatStartRequest(BaseModel):
    job_id: Optional[str] = None

    @field_validator("job_id")
    @classmethod
    def _strip_job_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChatStartResponse(BaseModel):
    chat_session_id: str


class ChatUIContext(BaseModel):
    page: str = "home"
    session_mode: str = "audio"
    status_message: str = "Not stated"
    has_audio_ready: bool = False
    job_status: Optional[str] = None
    active_result_tab: Optional[str] = None


class ChatMessageRequest(BaseModel):
    chat_session_id: str = Field(min_length=1)
    job_id: Optional[str] = None
    message: str = Field(min_length=1)
    autism_mode: bool = True
    include_prior_visits: bool = True
    ui_context: ChatUIContext = Field(default_factory=ChatUIContext)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be blank.")
        return cleaned

    @field_validator("job_id")
    @classmethod
    def _strip_optional_job_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChatMessageResponse(BaseModel):
    answer: str
    used_sources: list[UsedSource]
    follow_up_suggestions: list[str]
    safety_flag: bool = False
    delivery_note: Optional[str] = None


class ChatMessageStartResponse(BaseModel):
    assistant_message_id: int
    status: ChatMessageStatus
    answer: str
    used_sources: list[UsedSource]
    follow_up_suggestions: list[str]
    safety_flag: bool = False
    delivery_note: Optional[str] = None


class ChatHistoryItem(BaseModel):
    message_id: int
    role: ChatRole
    content: str
    created_at: str
    updated_at: str
    status: ChatMessageStatus = "final"
    used_sources: list[UsedSource] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    safety_flag: bool = False
    delivery_note: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    chat_session_id: str
    job_id: Optional[str]
    messages: list[ChatHistoryItem]


class ChatStreamEvent(BaseModel):
    type: Literal["draft_created", "message_updated", "message_finalized", "message_failed"]
    chat_session_id: str
    message_id: int
    status: ChatMessageStatus
    answer: str
    used_sources: list[UsedSource]
    follow_up_suggestions: list[str]
    safety_flag: bool = False
    delivery_note: Optional[str] = None
