from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    source_type: str
    request_json: str
    status: str
    progress: int
    stage_times: Dict[str, str]
    error: Optional[str]
    source_ref: Optional[str]
    conversation_id: Optional[str]
    audio_hash: Optional[str]
    source_hash: Optional[str]
    transcript_original: Optional[str]
    transcript_redacted: Optional[str]
    result_json: Optional[str]
    pdf_path: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class ChatSessionRecord:
    chat_session_id: str
    job_id: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class ChatMessageRecord:
    message_id: int
    chat_session_id: str
    role: str
    content: str
    status: str
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class JobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage_times_json TEXT NOT NULL,
                    error TEXT,
                    source_ref TEXT,
                    conversation_id TEXT,
                    audio_hash TEXT,
                    source_hash TEXT,
                    transcript_original TEXT,
                    transcript_redacted TEXT,
                    result_json TEXT,
                    pdf_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_audio_hash ON jobs(audio_hash);
                CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at);

                CREATE TABLE IF NOT EXISTS audio_cache (
                    audio_hash TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transcript_cache (
                    source_hash TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    chat_session_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_job_id ON chat_sessions(job_id);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'final'
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(chat_session_id);
                """
            )
            chat_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)").fetchall()
            }
            if "updated_at" not in chat_columns:
                connection.execute("ALTER TABLE chat_messages ADD COLUMN updated_at TEXT")
                connection.execute("UPDATE chat_messages SET updated_at = created_at WHERE updated_at IS NULL")
            if "status" not in chat_columns:
                connection.execute("ALTER TABLE chat_messages ADD COLUMN status TEXT DEFAULT 'final'")
                connection.execute("UPDATE chat_messages SET status = 'final' WHERE status IS NULL")

    def _row_to_job(self, row: Optional[sqlite3.Row]) -> Optional[JobRecord]:
        if row is None:
            return None
        return JobRecord(
            job_id=row["job_id"],
            source_type=row["source_type"],
            request_json=row["request_json"],
            status=row["status"],
            progress=row["progress"],
            stage_times=json.loads(row["stage_times_json"]),
            error=row["error"],
            source_ref=row["source_ref"],
            conversation_id=row["conversation_id"],
            audio_hash=row["audio_hash"],
            source_hash=row["source_hash"],
            transcript_original=row["transcript_original"],
            transcript_redacted=row["transcript_redacted"],
            result_json=row["result_json"],
            pdf_path=row["pdf_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_chat_session(self, row: Optional[sqlite3.Row]) -> Optional[ChatSessionRecord]:
        if row is None:
            return None
        return ChatSessionRecord(
            chat_session_id=row["chat_session_id"],
            job_id=row["job_id"] or None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_chat_message(self, row: sqlite3.Row) -> ChatMessageRecord:
        return ChatMessageRecord(
            message_id=row["message_id"],
            chat_session_id=row["chat_session_id"],
            role=row["role"],
            content=row["content"],
            status=row["status"] or "final",
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"] or row["created_at"],
        )

    def create_job(
        self,
        *,
        job_id: str,
        source_type: str,
        request_payload: dict[str, object],
        source_ref: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source_hash: Optional[str] = None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, source_type, request_json, status, progress, stage_times_json,
                    error, source_ref, conversation_id, audio_hash, source_hash,
                    transcript_original, transcript_redacted, result_json, pdf_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_type,
                    json.dumps(request_payload),
                    "QUEUED",
                    5,
                    json.dumps({"QUEUED": now}),
                    None,
                    source_ref,
                    conversation_id,
                    None,
                    source_hash,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row)

    def list_recoverable_jobs(self) -> List[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM jobs WHERE status NOT IN ('READY', 'FAILED') ORDER BY created_at ASC"
            ).fetchall()
        return [row["job_id"] for row in rows]

    def list_ready_jobs(self, *, exclude_job_id: Optional[str] = None, limit: int = 12) -> List[JobRecord]:
        query = "SELECT * FROM jobs WHERE status = 'READY'"
        params: list[Any] = []
        if exclude_job_id:
            query += " AND job_id != ?"
            params.append(exclude_job_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [job for row in rows if (job := self._row_to_job(row))]

    def update_stage(self, job_id: str, status: str, progress: int) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        stage_times = dict(job.stage_times)
        stage_times[status] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, stage_times_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, progress, json.dumps(stage_times), utc_now(), job_id),
            )

    def update_fields(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values()) + [utc_now(), job_id]
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE job_id = ?",
                values,
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        stage_times = dict(job.stage_times)
        stage_times["FAILED"] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'FAILED', progress = 100, error = ?, stage_times_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (error, json.dumps(stage_times), utc_now(), job_id),
            )

    def mark_ready(
        self,
        *,
        job_id: str,
        audio_hash: Optional[str],
        source_hash: Optional[str],
        conversation_id: Optional[str],
        transcript_original: str,
        transcript_redacted: str,
        result_json: str,
        pdf_path: str,
    ) -> None:
        job = self.get_job(job_id)
        if not job:
            return
        stage_times = dict(job.stage_times)
        stage_times["READY"] = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'READY', progress = 100, audio_hash = ?, source_hash = ?, conversation_id = ?,
                    transcript_original = ?, transcript_redacted = ?, result_json = ?, pdf_path = ?,
                    stage_times_json = ?, error = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    audio_hash,
                    source_hash,
                    conversation_id,
                    transcript_original,
                    transcript_redacted,
                    result_json,
                    pdf_path,
                    json.dumps(stage_times),
                    utc_now(),
                    job_id,
                ),
            )

            if audio_hash:
                connection.execute(
                    "INSERT OR REPLACE INTO audio_cache (audio_hash, job_id) VALUES (?, ?)",
                    (audio_hash, job_id),
                )
            if source_hash:
                connection.execute(
                    "INSERT OR REPLACE INTO transcript_cache (source_hash, job_id) VALUES (?, ?)",
                    (source_hash, job_id),
                )

    def hydrate_from_cached(
        self,
        *,
        target_job_id: str,
        cached_job: JobRecord,
        conversation_id: Optional[str] = None,
        audio_hash: Optional[str] = None,
        source_hash: Optional[str] = None,
    ) -> None:
        self.mark_ready(
            job_id=target_job_id,
            audio_hash=audio_hash or cached_job.audio_hash,
            source_hash=source_hash or cached_job.source_hash,
            conversation_id=conversation_id or cached_job.conversation_id,
            transcript_original=cached_job.transcript_original or "",
            transcript_redacted=cached_job.transcript_redacted or "",
            result_json=cached_job.result_json or "",
            pdf_path=cached_job.pdf_path or "",
        )

    def get_cached_job_by_audio_hash(self, audio_hash: str) -> Optional[JobRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT jobs.*
                FROM audio_cache
                JOIN jobs ON jobs.job_id = audio_cache.job_id
                WHERE audio_cache.audio_hash = ? AND jobs.status = 'READY'
                """,
                (audio_hash,),
            ).fetchone()
        return self._row_to_job(row)

    def get_cached_job_by_source_hash(self, source_hash: str) -> Optional[JobRecord]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT jobs.*
                FROM transcript_cache
                JOIN jobs ON jobs.job_id = transcript_cache.job_id
                WHERE transcript_cache.source_hash = ? AND jobs.status = 'READY'
                """,
                (source_hash,),
            ).fetchone()
        return self._row_to_job(row)

    def create_chat_session(self, *, chat_session_id: str, job_id: Optional[str]) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_sessions (chat_session_id, job_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_session_id, job_id or "", now, now),
            )

    def attach_chat_session_job(self, *, chat_session_id: str, job_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE chat_sessions SET job_id = ?, updated_at = ? WHERE chat_session_id = ?",
                (job_id, utc_now(), chat_session_id),
            )

    def get_chat_session(self, chat_session_id: str) -> Optional[ChatSessionRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chat_sessions WHERE chat_session_id = ?",
                (chat_session_id,),
            ).fetchone()
        return self._row_to_chat_session(row)

    def add_chat_message(
        self,
        *,
        chat_session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "final",
    ) -> ChatMessageRecord:
        metadata_json = json.dumps(metadata or {})
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO chat_messages (chat_session_id, role, content, metadata_json, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_session_id, role, content, metadata_json, now, now, status),
            )
            connection.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE chat_session_id = ?",
                (now, chat_session_id),
            )
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:  # pragma: no cover
            raise KeyError("Chat message could not be created.")
        return self._row_to_chat_message(row)

    def get_chat_message(self, message_id: int) -> Optional[ChatMessageRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_chat_message(row)

    def update_chat_message(
        self,
        *,
        message_id: int,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> Optional[ChatMessageRecord]:
        current = self.get_chat_message(message_id)
        if current is None:
            return None

        next_content = current.content if content is None else content
        next_metadata = current.metadata if metadata is None else metadata
        next_status = current.status if status is None else status
        updated_at = utc_now()

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE chat_messages
                SET content = ?, metadata_json = ?, status = ?, updated_at = ?
                WHERE message_id = ?
                """,
                (next_content, json.dumps(next_metadata), next_status, updated_at, message_id),
            )
            connection.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE chat_session_id = ?",
                (updated_at, current.chat_session_id),
            )
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:  # pragma: no cover
            return None
        return self._row_to_chat_message(row)

    def list_chat_messages(self, chat_session_id: str, *, limit: Optional[int] = None) -> List[ChatMessageRecord]:
        query = "SELECT * FROM chat_messages WHERE chat_session_id = ? ORDER BY message_id ASC"
        params: list[Any] = [chat_session_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._row_to_chat_message(row) for row in rows]

    def list_recent_chat_messages(self, chat_session_id: str, *, limit: int) -> List[ChatMessageRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM chat_messages
                    WHERE chat_session_id = ?
                    ORDER BY message_id DESC
                    LIMIT ?
                )
                ORDER BY message_id ASC
                """,
                (chat_session_id, limit),
            ).fetchall()
        return [self._row_to_chat_message(row) for row in rows]
