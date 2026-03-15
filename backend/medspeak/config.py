from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field


backend_env_path = Path(__file__).resolve().parent.parent / ".env"
repo_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(backend_env_path)
load_dotenv(repo_env_path, override=False)


class ConfigurationError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class _DefaultJobIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        return True


def configure_logging(level: str) -> None:
    logger = logging.getLogger("medspeak")
    if logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.addFilter(_DefaultJobIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [job_id=%(job_id)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def get_job_logger(job_id: str) -> logging.LoggerAdapter[Any]:
    return logging.LoggerAdapter(logging.getLogger("medspeak.worker"), extra={"job_id": job_id})


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    smallest_api_key: Optional[str] = None
    nim_api_key: Optional[str] = None
    nim_llm_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    nim_chat_model: str = "nvidia/llama-3.1-nemotron-nano-8b-v1"
    nim_embed_model: str = "nvidia/llama-nemotron-embed-1b-v2"
    nim_pii_model: str = "nvidia/gliner-pii"
    nim_rerank_model: str = "nvidia/llama-nemotron-rerank-1b-v2"
    use_qdrant: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    max_audio_seconds: int = 300
    redact_pii: bool = True
    enable_qa_agent_llm: bool = False
    request_timeout_seconds: float = 90.0
    worker_poll_seconds: float = 0.5
    worker_concurrency: int = 1
    public_base_url: Optional[str] = None
    log_level: str = "INFO"
    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
        ]
    )
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "medspeak_jobs.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"

    def ensure_nim_ready(self) -> None:
        if not self.nim_api_key:
            raise ConfigurationError("NIM_API_KEY is required for NVIDIA NIM calls.")

    def ensure_stt_ready(self) -> None:
        if not self.smallest_api_key:
            raise ConfigurationError("SMALLEST_API_KEY is required for smallest.ai transcription.")

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_origins = os.getenv(
            "ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001,http://localhost:3002,http://127.0.0.1:3002",
        )
        data_dir = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
        return cls(
            smallest_api_key=os.getenv("SMALLEST_API_KEY"),
            nim_api_key=os.getenv("NIM_API_KEY"),
            nim_llm_model=os.getenv("NIM_LLM_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
            nim_chat_model=os.getenv("NIM_CHAT_MODEL", "nvidia/llama-3.1-nemotron-nano-8b-v1"),
            nim_embed_model=os.getenv("NIM_EMBED_MODEL", "nvidia/llama-nemotron-embed-1b-v2"),
            nim_pii_model=os.getenv("NIM_PII_MODEL", "nvidia/gliner-pii"),
            nim_rerank_model=os.getenv("NIM_RERANK_MODEL", "nvidia/llama-nemotron-rerank-1b-v2"),
            use_qdrant=_parse_bool(os.getenv("USE_QDRANT"), False),
            qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            max_audio_seconds=int(os.getenv("MAX_AUDIO_SECONDS", "300")),
            redact_pii=_parse_bool(os.getenv("REDACT_PII"), True),
            enable_qa_agent_llm=_parse_bool(os.getenv("ENABLE_QA_AGENT_LLM"), False),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "90")),
            worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "0.5")),
            worker_concurrency=int(os.getenv("WORKER_CONCURRENCY", "1")),
            public_base_url=os.getenv("PUBLIC_BASE_URL"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            allowed_origins=[origin.strip() for origin in allowed_origins.split(",") if origin.strip()],
            data_dir=data_dir,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    return settings
