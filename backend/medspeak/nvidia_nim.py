from __future__ import annotations

import json
from typing import Any

import httpx

from medspeak.config import Settings


class NVIDIANIMError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        retryable: bool = False,
        response_preview: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.response_preview = response_preview


def _is_retryable_status(response: httpx.Response) -> bool:
    body = response.text.lower()
    if response.status_code in {408, 409, 425, 429}:
        return True
    if response.status_code >= 500:
        return True
    if "degraded function cannot be invoked" in body:
        return True
    if '"degraded"' in body and "cannot be invoked" in body:
        return True
    return False


def _headers(settings: Settings) -> dict[str, str]:
    settings.ensure_nim_ready()
    return {
        "Authorization": f"Bearer {settings.nim_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _response_preview(payload: Any, raw_text: str) -> str:
    if raw_text.strip():
        return raw_text[:400]
    try:
        return json.dumps(payload)[:400]
    except Exception:
        return ""


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            fragment = _extract_text_content(item)
            if fragment:
                fragments.append(fragment)
        return "\n".join(fragments).strip()
    if isinstance(content, dict):
        for key in ("text", "content", "value"):
            value = content.get(key)
            fragment = _extract_text_content(value)
            if fragment:
                return fragment
    return ""


def _extract_message_content(payload: Any, raw_text: str) -> str:
    try:
        choices = payload["choices"]
        message = choices[0]["message"]
    except Exception as exc:
        raise NVIDIANIMError(
            "NVIDIA chat completion returned an unexpected payload."
            + (f" Payload preview: {_response_preview(payload, raw_text)}" if _response_preview(payload, raw_text) else ""),
            retryable=True,
            response_preview=_response_preview(payload, raw_text),
        ) from exc

    content = _extract_text_content(message.get("content"))
    if content:
        return content

    raise NVIDIANIMError(
        "NVIDIA chat completion returned empty content."
        + (f" Payload preview: {_response_preview(payload, raw_text)}" if _response_preview(payload, raw_text) else ""),
        retryable=True,
        response_preview=_response_preview(payload, raw_text),
    )


def chat_completion(
    *,
    settings: Settings,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int = 3000,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=_headers(settings),
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise NVIDIANIMError("NVIDIA chat completion timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise NVIDIANIMError(f"NVIDIA chat completion request failed: {exc}", retryable=True) from exc

    if response.status_code >= 400:
        raise NVIDIANIMError(
            f"NVIDIA chat completion failed with status {response.status_code}: {response.text[:400]}",
            retryable=_is_retryable_status(response),
            response_preview=response.text[:400],
        )

    try:
        payload_data = response.json()
    except ValueError as exc:
        raise NVIDIANIMError(
            f"NVIDIA chat completion returned invalid JSON: {response.text[:400]}",
            retryable=True,
            response_preview=response.text[:400],
        ) from exc

    return _extract_message_content(payload_data, response.text)


def embed_texts(
    *,
    settings: Settings,
    texts: list[str],
    input_type: str,
) -> list[list[float]]:
    if not texts:
        return []
    payload = {
        "model": settings.nim_embed_model,
        "input": texts,
        "input_type": input_type,
        "encoding_format": "float",
        "truncate": "NONE",
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            "https://integrate.api.nvidia.com/v1/embeddings",
            headers=_headers(settings),
            json=payload,
        )

    if response.status_code >= 400:
        raise NVIDIANIMError(
            f"NVIDIA embeddings failed with status {response.status_code}: {response.text[:400]}",
            retryable=_is_retryable_status(response),
            response_preview=response.text[:400],
        )

    data = response.json().get("data", [])
    embeddings = sorted(data, key=lambda item: item.get("index", 0))
    return [item.get("embedding", []) for item in embeddings]


def rerank_indices(
    *,
    settings: Settings,
    query: str,
    documents: list[str],
    top_k: int = 5,
) -> list[int]:
    if not documents:
        return []

    payload = {
        "query": query,
        "passages": [{"text": document} for document in documents],
        "top_n": min(top_k, len(documents)),
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"https://ai.api.nvidia.com/v1/retrieval/{settings.nim_rerank_model}/reranking",
            headers=_headers(settings),
            json=payload,
        )

    if response.status_code >= 400:
        return list(range(min(top_k, len(documents))))

    data = response.json().get("rankings", [])
    ranked: list[int] = []
    for item in data:
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(documents):
            ranked.append(index)
    return ranked or list(range(min(top_k, len(documents))))


def rerank_documents(
    *,
    settings: Settings,
    query: str,
    documents: list[str],
    top_k: int = 5,
) -> list[str]:
    indexes = rerank_indices(settings=settings, query=query, documents=documents, top_k=top_k)
    return [documents[index] for index in indexes if 0 <= index < len(documents)]


def extract_pii_entities(*, settings: Settings, transcript: str) -> list[dict[str, str]]:
    prompt = (
        "Extract explicit PII or PHI mentions from the transcript. Return JSON only with the shape "
        '{"entities":[{"text":"string","label":"PERSON|EMAIL|PHONE|ADDRESS|ID|DOB"}]}. '
        "Use exact substrings from the transcript. Do not infer."
    )
    raw = chat_completion(
        settings=settings,
        model=settings.nim_pii_model,
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": f"{prompt}\n\nTranscript:\n{transcript}"},
        ],
        temperature=0,
        max_tokens=1200,
    )
    candidate = raw.strip()
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1:
            candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    entities = payload.get("entities", [])
    if not isinstance(entities, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        label = str(item.get("label", "")).strip().upper()
        if text:
            normalized.append({"text": text, "label": label or "PII"})
    return normalized
