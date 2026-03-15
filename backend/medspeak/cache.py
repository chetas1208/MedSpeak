from __future__ import annotations

import hashlib
from typing import Optional

from medspeak.jobs import JobRecord, JobStore


def compute_transcript_hash(transcript: str) -> str:
    return hashlib.sha256(f"transcript:{transcript.strip()}".encode("utf-8")).hexdigest()


def find_cached_audio_job(job_store: JobStore, audio_hash: str) -> Optional[JobRecord]:
    return job_store.get_cached_job_by_audio_hash(audio_hash)


def find_cached_transcript_job(job_store: JobStore, transcript_hash: str) -> Optional[JobRecord]:
    return job_store.get_cached_job_by_source_hash(transcript_hash)
