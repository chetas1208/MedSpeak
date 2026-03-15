from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from main import create_app
from medspeak import audio_utils, llm_prompt, nvidia_nim, pdf_export, schema, smallest_stt, vector_store
from medspeak.config import Settings


def sample_result_payload() -> dict:
    return {
        "standard_summary": "The clinician reviewed symptoms and discussed a follow-up blood test.",
        "autism_friendly_summary": "1. The visit reviewed symptoms.\n2. A blood test was discussed.\n3. Date not stated.",
        "intent_summary": [
            "Symptoms were discussed at the start of the visit.",
            "A blood test and follow-up plan were discussed later in the visit.",
        ],
        "intent_timeline": [
            {
                "start": "00:00",
                "end": "00:07",
                "speaker": "SPEAKER_0",
                "text": "I have been tired and dizzy this week.",
                "intents": ["SYMPTOMS"],
                "confidence": 0.98,
            },
            {
                "start": "00:07",
                "end": "00:14",
                "speaker": "SPEAKER_1",
                "text": "We can order a blood test and follow up after that.",
                "intents": ["TEST_OR_LAB_ORDER", "FOLLOW_UP_PLAN"],
                "confidence": 0.96,
            },
        ],
        "next_steps_checklist": [{"step": "blood test", "who": "clinician", "when": "Not stated"}],
        "medications": [
            {
                "name": "Not stated",
                "dose": "Not stated",
                "frequency": "Not stated",
                "purpose": "Not stated",
                "notes": "Not stated",
            }
        ],
        "tests_and_referrals": [{"item": "blood test", "purpose": "follow up", "when": "Not stated"}],
        "red_flags": ["Not stated"],
        "questions_to_ask": ["When is the blood test?"],
        "accommodation_card": {
            "summary": "Use direct explanations and written steps.",
            "communication": ["Use direct language."],
            "sensory": ["Quiet room if available."],
            "processing": ["Allow extra time."],
            "support": ["Caregiver can stay in the room."],
        },
        "social_scripts": [
            {
                "situation": "Asking for a repeat explanation",
                "script": "Please say that again in a shorter way.",
            }
        ],
        "uncertainties": ["The exact date of the blood test was not stated."],
        "safety_note": "This is for note-taking and clarity, not medical advice.",
    }


def make_settings(tmp_path: Path, redact_pii: bool = True) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        smallest_api_key="smallest-key",
        nim_api_key="nim-key",
        use_qdrant=False,
        redact_pii=redact_pii,
        request_timeout_seconds=5,
        worker_poll_seconds=0.05,
        data_dir=data_dir,
        public_base_url="http://localhost:8000",
    )


class FakeEmbeddingResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class FakeEmbeddingClient:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def __enter__(self) -> "FakeEmbeddingClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict, json: dict) -> FakeEmbeddingResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return FakeEmbeddingResponse(200, {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})


class FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict | list | None = None, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self) -> dict | list:
        if self._payload is None:
            raise ValueError("No JSON payload.")
        return self._payload


class FakeSequenceClient:
    def __init__(self, responses: list[FakeHTTPResponse], calls: list[dict]) -> None:
        self.responses = responses
        self.calls = calls

    def __enter__(self) -> "FakeSequenceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, headers: dict | None = None, json: dict | None = None, **kwargs) -> FakeHTTPResponse:
        self.calls.append({"url": url, "headers": headers or {}, "json": json, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("No fake responses left.")
        return self.responses.pop(0)


class FakePoint:
    def __init__(self, point_id: str, payload: dict, score: float = 0.72) -> None:
        self.id = point_id
        self.payload = payload
        self.score = score


class FakeCollectionInfo:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeQdrantClient:
    def __init__(self, *args, **kwargs) -> None:
        self.collections: dict[str, list] = {}
        self.created_collections: list[str] = []
        self.upserted_points: list = []

    def get_collection(self, collection_name: str):
        if collection_name not in self.collections:
            raise RuntimeError("missing collection")
        return FakeCollectionInfo(collection_name)

    def create_collection(self, collection_name: str, vectors_config) -> None:
        self.created_collections.append(collection_name)
        self.collections[collection_name] = []

    def search(self, collection_name: str, query_vector: list[float], limit: int, with_payload: bool):
        del query_vector, limit, with_payload
        return [
            FakePoint(
                point_id=str(index),
                payload=payload,
            )
            for index, payload in enumerate(self.collections.get(collection_name, []))
        ]

    def upsert(self, collection_name: str, points: list) -> None:
        self.upserted_points.extend(points)
        self.collections.setdefault(collection_name, []).extend(point.payload for point in points)


def transcript_payload(transcript: str) -> dict:
    return {
        "transcript": transcript,
        "autism_mode": True,
        "preferences": schema.Preferences().model_dump(),
        "language": "en",
    }


def audio_form_payload() -> dict:
    return {"autism_mode": True, "preferences": schema.Preferences().model_dump(), "language": "en"}


def poll_job(client: TestClient, job_id: str, timeout: float = 4.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/job/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"READY", "FAILED"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for job {job_id}")


def patch_common_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, messages, temperature, max_tokens
        return json.dumps(sample_result_payload())

    def fake_extract_pii_entities(*, settings: Settings, transcript: str) -> list:
        del settings
        return [{"text": "Jamie Rivera", "label": "PERSON"}] if "Jamie Rivera" in transcript else []

    def fake_pdf(*, job_id: str, result: schema.AnalysisResult, transcript: str, output_dir: Path, logger) -> Path:
        del result, transcript, logger
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 test")
        return pdf_path

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)
    monkeypatch.setattr("medspeak.nvidia_nim.extract_pii_entities", fake_extract_pii_entities)
    monkeypatch.setattr("medspeak.agent_worker.generate_pdf_report", fake_pdf)


def test_health_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("medspeak.audio_utils.is_ffmpeg_available", lambda: True)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "ffmpeg_available": True,
        "use_qdrant": False,
        "worker_running": True,
    }


def test_embed_texts_sends_required_input_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(nvidia_nim.httpx, "Client", lambda timeout: FakeEmbeddingClient(calls))

    embeddings = nvidia_nim.embed_texts(settings=settings, texts=["blood test follow up"], input_type="query")

    assert embeddings == [[0.1, 0.2, 0.3]]
    assert calls[0]["json"]["input_type"] == "query"
    assert calls[0]["json"]["truncate"] == "NONE"
    assert calls[0]["json"]["encoding_format"] == "float"


def test_chat_completion_accepts_plain_string_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls: list[dict] = []
    responses = [
        FakeHTTPResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "{\"ok\":true}",
                        }
                    }
                ]
            },
        )
    ]
    monkeypatch.setattr(nvidia_nim.httpx, "Client", lambda timeout: FakeSequenceClient(responses, calls))

    content = nvidia_nim.chat_completion(
        settings=settings,
        model=settings.nim_llm_model,
        messages=[{"role": "user", "content": "Return JSON only."}],
    )

    assert content == "{\"ok\":true}"


def test_chat_completion_accepts_structured_content_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls: list[dict] = []
    responses = [
        FakeHTTPResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "{\"ok\":true}"},
                            ],
                        }
                    }
                ]
            },
        )
    ]
    monkeypatch.setattr(nvidia_nim.httpx, "Client", lambda timeout: FakeSequenceClient(responses, calls))

    content = nvidia_nim.chat_completion(
        settings=settings,
        model=settings.nim_llm_model,
        messages=[{"role": "user", "content": "Return JSON only."}],
    )

    assert content == "{\"ok\":true}"


def test_transcribe_wav_retries_transient_service_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls: list[dict] = []
    responses = [
        FakeHTTPResponse(
            403,
            {"status": "error", "message": "Service temporarily unavailable. Please try again."},
            text='{"status":"error","message":"Service temporarily unavailable. Please try again."}',
        ),
        FakeHTTPResponse(
            200,
            {
                "transcription": "Please schedule a blood test.",
                "utterances": [{"start": 0, "end": 4, "speaker": 0, "text": "Please schedule a blood test."}],
            },
        ),
    ]
    monkeypatch.setattr(smallest_stt.httpx, "Client", lambda timeout: FakeSequenceClient(responses, calls))
    monkeypatch.setattr(smallest_stt.time, "sleep", lambda _: None)
    logger_messages: list[str] = []
    logger = type("Logger", (), {"info": lambda self, message, *args: logger_messages.append(message % args)})()

    result = smallest_stt.transcribe_wav(
        wav_bytes=b"fake-wav",
        language="en",
        settings=settings,
        logger=logger,
    )

    assert result.transcript == "[00:00-00:04] SPEAKER_0: Please schedule a blood test."
    assert len(calls) == 2
    assert any("Retrying smallest.ai transcription" in message for message in logger_messages)


def test_transcribe_wav_does_not_retry_auth_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls: list[dict] = []
    responses = [
        FakeHTTPResponse(
            403,
            {"status": "error", "message": "Forbidden"},
            text='{"status":"error","message":"Forbidden"}',
        ),
    ]
    monkeypatch.setattr(smallest_stt.httpx, "Client", lambda timeout: FakeSequenceClient(responses, calls))
    monkeypatch.setattr(smallest_stt.time, "sleep", lambda _: None)
    logger = type("Logger", (), {"info": lambda self, message, *args: None})()

    with pytest.raises(smallest_stt.SmallestSTTError) as exc_info:
        smallest_stt.transcribe_wav(
            wav_bytes=b"fake-wav",
            language="en",
            settings=settings,
            logger=logger,
        )

    assert "authentication or authorization" in str(exc_info.value)
    assert len(calls) == 1


def test_vector_store_uses_query_for_retrieval_and_passage_for_indexing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    settings.use_qdrant = True
    fake_client = FakeQdrantClient()
    input_types: list[str] = []

    monkeypatch.setattr(vector_store, "QdrantClient", lambda **kwargs: fake_client)

    def fake_embed_texts(*, settings: Settings, texts: list[str], input_type: str) -> list[list[float]]:
        del settings, texts
        input_types.append(input_type)
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", fake_embed_texts)
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: [0])

    store = vector_store.VectorStore(settings)
    fake_client.collections[store.collection_name] = [
        {
            "visit_id": "prior-job",
            "chunk_id": "prior-visit-prior-job-0",
            "source_type": "prior_visit",
            "text": "From prior visit record: blood test follow up.",
        }
    ]

    docs = store.retrieve_context(query="blood test follow up", exclude_job_id="current-job")
    store.index_transcript(job_id="current-job", conversation_id=None, transcript="[00:00-00:05] SPEAKER_0: blood test follow up")

    assert docs == ["From prior visit record: blood test follow up."]
    assert input_types == ["query", "passage"]
    assert len(fake_client.upserted_points) > 0
    UUID(str(fake_client.upserted_points[0].id))


def test_transcript_cache_hit_reuses_ready_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    patch_common_pipeline(monkeypatch)
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/analyze_from_transcript", json=transcript_payload("Same transcript."))
        first_job = poll_job(client, first.json()["job_id"])
        second = client.post("/api/analyze_from_transcript", json=transcript_payload("Same transcript."))

    assert first_job["status"] == "READY"
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]


def test_transcript_job_redacts_pii_and_serves_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, redact_pii=True)
    patch_common_pipeline(monkeypatch)
    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload("Jamie Rivera said call 415-555-1212 or email jamie@example.com at 123 Main Street."),
        )
        job = poll_job(client, enqueue.json()["job_id"])
        download = client.get(f"/api/download/{job['job_id']}.pdf")

    assert job["status"] == "READY"
    assert "Jamie Rivera" in job["transcript_redacted"]
    assert "[REDACTED_PHONE]" in job["transcript_redacted"]
    assert "[REDACTED_EMAIL]" in job["transcript_redacted"]
    assert "[REDACTED_ADDRESS]" in job["transcript_redacted"]
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"


def test_transcript_job_normalizes_generic_speakers_to_patient_and_doctor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, redact_pii=True)
    patch_common_pipeline(monkeypatch)

    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload(
                "[00:00-00:07] SPEAKER_0: I have been tired this week.\n[00:07-00:14] SPEAKER_1: We will order a blood test."
            ),
        )
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert job["transcript_redacted"].startswith("[00:00-00:07] Patient:")
    assert "Doctor" in job["transcript_redacted"]
    assert job["result_json"]["intent_timeline"][0]["speaker"] == "Patient"
    assert job["result_json"]["intent_timeline"][1]["speaker"] == "Doctor"


def test_transcript_job_keeps_explicit_names_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, redact_pii=True)
    patch_common_pipeline(monkeypatch)

    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload(
                "[00:00-00:07] Maya Rivera: I have been tired this week.\n[00:07-00:14] Dr. Chen: We will order a blood test."
            ),
        )
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert "Maya Rivera" in job["transcript_redacted"]
    assert "Dr. Chen" in job["transcript_redacted"]


def test_transcript_job_can_return_original_when_redaction_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path, redact_pii=False)
    patch_common_pipeline(monkeypatch)
    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload("Please call 415-555-1212 after the visit."),
        )
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert job["transcript_redacted"] == "Please call 415-555-1212 after the visit."


def test_transcript_job_with_qdrant_indexing_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, redact_pii=True)
    settings.use_qdrant = True
    fake_client = FakeQdrantClient()
    embed_types: list[str] = []

    monkeypatch.setattr(vector_store, "QdrantClient", lambda **kwargs: fake_client)
    patch_common_pipeline(monkeypatch)

    def fake_embed_texts(*, settings: Settings, texts: list[str], input_type: str) -> list[list[float]]:
        del settings
        embed_types.append(input_type)
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", fake_embed_texts)
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: list(range(min(kwargs["top_k"], len(kwargs["documents"])))))

    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload("Jamie Rivera discussed dizziness and a blood test follow up."),
        )
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert "passage" in embed_types
    assert fake_client.created_collections == ["medspeak_transcripts"]
    assert len(fake_client.upserted_points) > 0
    UUID(str(fake_client.upserted_points[0].id))


def test_invalid_json_is_repaired_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    prompts = []
    responses = iter(["not json at all", json.dumps(sample_result_payload())])

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, temperature, max_tokens
        prompts.append(messages)
        return next(responses)

    def fake_pdf(*, job_id: str, result: schema.AnalysisResult, transcript: str, output_dir: Path, logger) -> Path:
        del result, transcript, logger
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 repaired")
        return pdf_path

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)
    monkeypatch.setattr("medspeak.nvidia_nim.extract_pii_entities", lambda **kwargs: [])
    monkeypatch.setattr("medspeak.agent_worker.generate_pdf_report", fake_pdf)

    with TestClient(create_app(settings)) as client:
        enqueue = client.post("/api/analyze_from_transcript", json=transcript_payload("Simple transcript."))
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert len(prompts) == 2
    assert llm_prompt.FIX_JSON_PROMPT in prompts[1][1]["content"]


def test_analysis_retries_retryable_empty_nim_response_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(tmp_path)
    calls = {"llm": 0}

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, messages, temperature, max_tokens
        calls["llm"] += 1
        if calls["llm"] == 1:
            raise nvidia_nim.NVIDIANIMError("NVIDIA chat completion returned empty content.", retryable=True)
        return json.dumps(sample_result_payload())

    def fake_pdf(*, job_id: str, result: schema.AnalysisResult, transcript: str, output_dir: Path, logger) -> Path:
        del result, transcript, logger
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 repaired")
        return pdf_path

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)
    monkeypatch.setattr("medspeak.nvidia_nim.extract_pii_entities", lambda **kwargs: [])
    monkeypatch.setattr("medspeak.agent_worker.generate_pdf_report", fake_pdf)

    with TestClient(create_app(settings)) as client:
        enqueue = client.post("/api/analyze_from_transcript", json=transcript_payload("Symptoms and a blood test follow up."))
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "READY"
    assert calls["llm"] == 2


def test_audio_hash_reuse_copies_cached_result_to_new_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    calls = {"normalize": 0, "stt": 0, "llm": 0}

    def fake_normalize(*, audio_bytes: bytes, content_type: str, filename: str, max_audio_seconds: int):
        del audio_bytes, content_type, filename, max_audio_seconds
        calls["normalize"] += 1
        return audio_utils.NormalizedAudio(wav_bytes=b"wav", audio_hash="shared-audio-hash", duration_seconds=9.0)

    def fake_stt(*, wav_bytes: bytes, language: str, settings: Settings, logger):
        del wav_bytes, language, settings, logger
        calls["stt"] += 1
        return smallest_stt.STTResult(
            transcription="Symptoms and blood test follow up.",
            transcript="[00:00-00:07] SPEAKER_0: Symptoms.\n[00:07-00:14] SPEAKER_1: blood test follow up.",
            raw_response={},
        )

    def fake_llm(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, messages, temperature, max_tokens
        calls["llm"] += 1
        return json.dumps(sample_result_payload())

    def fake_pdf(*, job_id: str, result: schema.AnalysisResult, transcript: str, output_dir: Path, logger) -> Path:
        del result, transcript, logger
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{job_id}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 reuse")
        return pdf_path

    monkeypatch.setattr("medspeak.audio_utils.normalize_audio_bytes", fake_normalize)
    monkeypatch.setattr("medspeak.smallest_stt.transcribe_wav", fake_stt)
    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_llm)
    monkeypatch.setattr("medspeak.nvidia_nim.extract_pii_entities", lambda **kwargs: [])
    monkeypatch.setattr("medspeak.agent_worker.generate_pdf_report", fake_pdf)

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/analyze_from_audio",
            files={"audio": ("visit-a.webm", b"fake-bytes-a", "audio/webm")},
            data={"payload": json.dumps(audio_form_payload())},
        )
        first_job = poll_job(client, first.json()["job_id"])
        second = client.post(
            "/api/analyze_from_audio",
            files={"audio": ("visit-b.webm", b"fake-bytes-b", "audio/webm")},
            data={"payload": json.dumps(audio_form_payload())},
        )
        second_job = poll_job(client, second.json()["job_id"])

    assert first_job["status"] == "READY"
    assert second_job["status"] == "READY"
    assert first.json()["job_id"] != second.json()["job_id"]
    assert second_job["result_json"]["standard_summary"] == first_job["result_json"]["standard_summary"]
    assert calls == {"normalize": 2, "stt": 1, "llm": 1}


def test_audio_too_long_marks_job_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)

    def fake_normalize(**kwargs):
        raise audio_utils.AudioTooLongError(duration_seconds=360.0, limit_seconds=300)

    monkeypatch.setattr("medspeak.audio_utils.normalize_audio_bytes", fake_normalize)

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/analyze_from_audio",
            files={"audio": ("visit.webm", b"fake-bytes", "audio/webm")},
            data={"payload": json.dumps(audio_form_payload())},
        )
        job = poll_job(client, response.json()["job_id"])

    assert job["status"] == "FAILED"
    assert "current limit is 300 seconds" in job["error"]


def test_missing_ffmpeg_marks_job_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    monkeypatch.setattr(
        "medspeak.audio_utils.normalize_audio_bytes",
        lambda **kwargs: (_ for _ in ()).throw(audio_utils.AudioProcessingError("ffmpeg is not installed or not on PATH.")),
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/analyze_from_audio",
            files={"audio": ("visit.webm", b"fake-bytes", "audio/webm")},
            data={"payload": json.dumps(audio_form_payload())},
        )
        job = poll_job(client, response.json()["job_id"])

    assert job["status"] == "FAILED"
    assert "ffmpeg is not installed or not on PATH" in job["error"]


def test_failed_job_keeps_redacted_transcript_for_debugging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, redact_pii=True)

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, messages, temperature, max_tokens
        raise nvidia_nim.NVIDIANIMError("NVIDIA chat completion returned empty content.", retryable=True)

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        "medspeak.nvidia_nim.extract_pii_entities",
        lambda **kwargs: [{"text": "Jamie Rivera", "label": "PERSON"}],
    )

    with TestClient(create_app(settings)) as client:
        enqueue = client.post(
            "/api/analyze_from_transcript",
            json=transcript_payload("Jamie Rivera discussed dizziness and a blood test follow up."),
        )
        job = poll_job(client, enqueue.json()["job_id"])

    assert job["status"] == "FAILED"
    assert "Jamie Rivera" in (job["transcript_redacted"] or "")


def test_pdf_sections_include_intent_timeline_and_transcript() -> None:
    sections = pdf_export.build_report_sections(
        result=schema.AnalysisResult.model_validate(sample_result_payload()),
        transcript="[00:00-00:08] SPEAKER_0: Please schedule the blood test.",
    )

    section_lookup = {title: rows for title, rows in sections}
    assert "Intent Timeline" in section_lookup
    assert any("Patient" in row for row in section_lookup["Intent Timeline"])
    assert "Full Redacted Transcript" in section_lookup
    assert section_lookup["Full Redacted Transcript"][0].startswith("[00:00-00:08] Patient")
