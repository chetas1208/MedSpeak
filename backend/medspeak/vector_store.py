from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
from typing import Iterable, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest

from medspeak import nvidia_nim
from medspeak.config import Settings


@dataclass
class RetrievedChunk:
    source_type: str
    visit_id: str
    chunk_id: str
    text: str
    score: float


def chunk_text(text: str, *, max_chars: int = 900) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines and text.strip():
        lines = [text.strip()]

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return chunks


class VectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.collection_name = "medspeak_transcripts"
        self.client = (
            QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
                timeout=settings.request_timeout_seconds,
            )
            if settings.use_qdrant
            else None
        )

    def retrieve_context(self, *, query: str, exclude_job_id: Optional[str] = None, top_k: int = 4) -> List[str]:
        return [item.text for item in self.search_prior_chunks(query=query, exclude_job_id=exclude_job_id, top_k=top_k)]

    def search_prior_chunks(
        self,
        *,
        query: str,
        exclude_job_id: Optional[str] = None,
        top_k: int = 4,
    ) -> List[RetrievedChunk]:
        if not self.settings.use_qdrant or not self.client:
            return []

        try:
            embeddings = nvidia_nim.embed_texts(
                settings=self.settings,
                texts=[query[:4000]],
                input_type="query",
            )
        except Exception:
            return []
        if not embeddings or not embeddings[0]:
            return []

        try:
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=embeddings[0],
                limit=top_k * 3,
                with_payload=True,
            )
        except Exception:
            return []

        documents: list[RetrievedChunk] = []
        for point in search_result:
            payload = point.payload or {}
            visit_id = str(payload.get("visit_id") or payload.get("job_id") or "")
            if exclude_job_id and visit_id == exclude_job_id:
                continue
            text = str(payload.get("text", "")).strip()
            if not text:
                continue
            documents.append(
                RetrievedChunk(
                    source_type=str(payload.get("source_type") or "prior_visit"),
                    visit_id=visit_id or "Not stated",
                    chunk_id=str(payload.get("chunk_id") or point.id),
                    text=text,
                    score=float(getattr(point, "score", 0.0) or 0.0),
                )
            )
        reranked_ids = nvidia_nim.rerank_indices(
            settings=self.settings,
            query=query[:4000],
            documents=[item.text for item in documents],
            top_k=top_k,
        )
        return [documents[index] for index in reranked_ids if 0 <= index < len(documents)]

    def index_transcript(
        self,
        *,
        job_id: str,
        conversation_id: Optional[str],
        transcript: str,
    ) -> None:
        if not self.settings.use_qdrant or not self.client:
            return

        chunks = chunk_text(transcript)
        if not chunks:
            return

        embeddings = nvidia_nim.embed_texts(
            settings=self.settings,
            texts=chunks,
            input_type="passage",
        )
        if not embeddings or not embeddings[0]:
            return

        try:
            self.client.get_collection(self.collection_name)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=rest.VectorParams(size=len(embeddings[0]), distance=rest.Distance.COSINE),
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        points = [
            rest.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{job_id}:{index}:{chunk}")),
                vector=embedding,
                payload={
                    "job_id": job_id,
                    "visit_id": job_id,
                    "conversation_id": conversation_id or "Not stated",
                    "chunk_id": f"prior-visit-{job_id}-{index}",
                    "chunk_index": index,
                    "source_type": "prior_visit",
                    "text": chunk,
                    "created_at": timestamp,
                },
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)
