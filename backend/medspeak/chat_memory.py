from __future__ import annotations

import json
from uuid import uuid4

from medspeak.chat_schema import ChatHistoryItem, ChatHistoryResponse, ChatStartResponse
from medspeak.jobs import JobStore


class ChatMemoryService:
    def __init__(self, job_store: JobStore) -> None:
        self.job_store = job_store

    def start_session(self, *, job_id: str | None) -> ChatStartResponse:
        chat_session_id = uuid4().hex
        self.job_store.create_chat_session(chat_session_id=chat_session_id, job_id=job_id)
        return ChatStartResponse(chat_session_id=chat_session_id)

    def get_history(self, *, chat_session_id: str) -> ChatHistoryResponse:
        session = self.job_store.get_chat_session(chat_session_id)
        if not session:
            raise KeyError("Chat session not found.")
        messages = [
            ChatHistoryItem(
                message_id=message.message_id,
                role=message.role,  # type: ignore[arg-type]
                content=message.content,
                created_at=message.created_at,
                updated_at=message.updated_at,
                status=message.status,  # type: ignore[arg-type]
                used_sources=message.metadata.get("used_sources", []),
                follow_up_suggestions=message.metadata.get("follow_up_suggestions", []),
                safety_flag=bool(message.metadata.get("safety_flag", False)),
                delivery_note=message.metadata.get("delivery_note"),
            )
            for message in self.job_store.list_chat_messages(chat_session_id)
        ]
        return ChatHistoryResponse(chat_session_id=chat_session_id, job_id=session.job_id, messages=messages)

    def append_user_message(self, *, chat_session_id: str, content: str) -> None:
        self.job_store.add_chat_message(chat_session_id=chat_session_id, role="user", content=content, status="final")

    def append_assistant_message(
        self,
        *,
        chat_session_id: str,
        content: str,
        metadata: dict[str, object],
    ) -> None:
        self.job_store.add_chat_message(
            chat_session_id=chat_session_id,
            role="assistant",
            content=content,
            metadata=metadata,
            status="final",
        )

    def recent_history_for_prompt(self, *, chat_session_id: str, limit: int = 6) -> list[dict[str, str]]:
        messages = self.job_store.list_recent_chat_messages(chat_session_id, limit=limit)
        return [{"role": message.role, "content": message.content} for message in messages]
