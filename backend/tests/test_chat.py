from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import create_app
from medspeak import chat_prompt, schema
from medspeak.chat_schema import UnsupportedAnswer
from medspeak.config import Settings
from medspeak.nvidia_nim import NVIDIANIMError


def make_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        smallest_api_key="smallest-key",
        nim_api_key="nim-key",
        use_qdrant=False,
        request_timeout_seconds=5,
        worker_poll_seconds=0.05,
        data_dir=data_dir,
        public_base_url="http://localhost:8000",
    )


def sample_result() -> schema.AnalysisResult:
    return schema.AnalysisResult.model_validate(
        {
            "standard_summary": "The clinician discussed dizziness and a blood test.",
            "autism_friendly_summary": "1. Dizziness was discussed.\n2. A blood test was discussed.\n3. Date not stated.",
            "intent_summary": ["Symptoms were reviewed.", "A blood test was discussed."],
            "intent_timeline": [
                {
                    "start": "00:00",
                    "end": "00:06",
                    "speaker": "SPEAKER_0",
                    "text": "I feel dizzy.",
                    "intents": ["SYMPTOMS"],
                    "confidence": 0.95,
                }
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
            "questions_to_ask": ["What happens after the blood test?"],
            "accommodation_card": {
                "summary": "Direct explanations help.",
                "communication": ["Use direct language."],
                "sensory": ["Quiet room."],
                "processing": ["Written steps."],
                "support": ["Caregiver can stay."],
            },
            "social_scripts": [{"situation": "Need clarification", "script": "Please explain that in a shorter way."}],
            "uncertainties": ["The date was not stated."],
            "safety_note": "This is for note-taking and clarity, not medical advice.",
        }
    )


def seed_ready_job(client: TestClient, *, job_id: str, transcript: str, preferences: dict, result: schema.AnalysisResult) -> None:
    store = client.app.state.job_store
    pdf_dir = client.app.state.settings.pdf_dir
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{job_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 chat")
    store.create_job(
        job_id=job_id,
        source_type="transcript",
        request_payload={
            "transcript": transcript,
            "autism_mode": True,
            "preferences": preferences,
            "language": "en",
        },
        source_hash=f"hash-{job_id}",
    )
    store.mark_ready(
        job_id=job_id,
        audio_hash=None,
        source_hash=f"hash-{job_id}",
        conversation_id=None,
        transcript_original=transcript,
        transcript_redacted=transcript,
        result_json=result.model_dump_json(),
        pdf_path=str(pdf_path),
    )


def start_session(client: TestClient, job_id: str | None = None) -> str:
    payload = {"job_id": job_id} if job_id is not None else {}
    response = client.post("/api/chat/start", json=payload)
    assert response.status_code == 200
    return response.json()["chat_session_id"]


def wait_for_message_status(
    client: TestClient,
    *,
    chat_session_id: str,
    message_id: int,
    status: str,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_message: dict[str, object] | None = None
    while time.time() < deadline:
        history = client.get(f"/api/chat/history/{chat_session_id}")
        assert history.status_code == 200
        messages = history.json()["messages"]
        for item in messages:
            if item["message_id"] == message_id:
                last_message = item
                if item["status"] == status:
                    return item
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for message {message_id} to reach {status}. Last value: {last_message}")


def test_grounded_chat_answer_returns_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()

    def fake_embed_texts(*, settings: Settings, texts: list[str], input_type: str) -> list[list[float]]:
        del settings, input_type
        return [[0.2, 0.4, 0.6] for _ in texts]

    def fake_rerank_indices(*, settings: Settings, query: str, documents: list[str], top_k: int) -> list[int]:
        del settings, query
        return list(range(min(top_k, len(documents))))

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del temperature, max_tokens
        assert model == settings.nim_chat_model
        return json.dumps(
            {
                "answer": "1. First, complete the blood test.\n2. The date was not stated.",
                "used_sources": [
                    {
                        "source_type": "current_result",
                        "chunk_id": "result-next-steps",
                        "visit_id": "job-current",
                        "quote": "Next steps: blood test | who: clinician | when: Not stated",
                    }
                ],
                "follow_up_suggestions": [
                    "Explain this simply.",
                    "What happens after the blood test?",
                    "Help me prepare a follow-up question.",
                ],
                "safety_flag": False,
            }
        )

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", fake_embed_texts)
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", fake_rerank_indices)
    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What should I do first?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )
        history = client.get(f"/api/chat/history/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("1. blood test. who: clinician. when: Not stated")
    assert payload["used_sources"][0]["chunk_id"] == "result-next-steps"
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2


def test_site_context_answer_is_available_before_any_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", lambda **kwargs: [[0.2, 0.4, 0.6] for _ in kwargs["texts"]])
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: list(range(min(kwargs["top_k"], len(kwargs["documents"])))))
    monkeypatch.setattr(
        "medspeak.nvidia_nim.chat_completion",
        lambda **kwargs: json.dumps(
            {
                "answer": "1. First, record in the browser or upload audio.\n2. Then run analysis.\n3. Review the results after the job is ready.",
                "used_sources": [
                    {
                        "source_type": "site_context",
                        "chunk_id": "site-workflow",
                        "visit_id": "site",
                        "quote": "The main workflow is: record locally or upload audio, choose autism mode and preferences, run analysis, wait for queued job stages, review results, and open the companion chat for grounded follow-up.",
                    }
                ],
                "follow_up_suggestions": [
                    "How do I upload audio?",
                    "What does the status rail mean?",
                    "When can I open the PDF?",
                ],
                "safety_flag": False,
            }
        ),
    )

    with TestClient(create_app(settings)) as client:
        session_id = start_session(client)
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "message": "What should I do first?",
                "autism_mode": True,
                "include_prior_visits": True,
                "ui_context": {
                    "page": "home",
                    "session_mode": "audio",
                    "status_message": "Ready to record or upload audio.",
                    "has_audio_ready": False,
                    "job_status": None,
                    "active_result_tab": None,
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["used_sources"][0]["source_type"] == "site_context"
    assert payload["answer"].startswith("1. Record locally or upload audio.")


def test_unsupported_question_falls_back_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", lambda **kwargs: [[0.2, 0.4, 0.6] for _ in kwargs["texts"]])
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: [0, 1, 2])
    monkeypatch.setattr(
        "medspeak.nvidia_nim.chat_completion",
        lambda **kwargs: json.dumps(
            {
                "answer": UnsupportedAnswer,
                "used_sources": [],
                "follow_up_suggestions": ["Explain this simply.", "What should I do first?", "Help me prepare a follow-up question."],
                "safety_flag": True,
            }
        ),
    )

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What illness do I have?",
                "autism_mode": True,
                "include_prior_visits": False,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == UnsupportedAnswer
    assert payload["safety_flag"] is True


def test_visit_question_before_any_visit_context_falls_back_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        session_id = start_session(client)
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "message": "What did they say about medication?",
                "autism_mode": True,
                "include_prior_visits": True,
                "ui_context": {
                    "page": "home",
                    "session_mode": "audio",
                    "status_message": "No job yet.",
                    "has_audio_ready": False,
                    "job_status": None,
                    "active_result_tab": None,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["answer"] == UnsupportedAnswer


def test_prior_visit_context_can_be_used_and_labeled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()
    prompts: list[str] = []

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", lambda **kwargs: [[0.2, 0.4, 0.6] for _ in kwargs["texts"]])
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: list(range(min(kwargs["top_k"], len(kwargs["documents"])))))

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, temperature, max_tokens
        prompts.append(messages[1]["content"])
        return json.dumps(
            {
                "answer": "From a prior visit record, dizziness was also discussed before. In this visit, the blood test is the new recorded plan.",
                "used_sources": [
                    {
                        "source_type": "prior_visit",
                        "chunk_id": "prior-transcript-job-prior-0",
                        "visit_id": "job-prior",
                        "quote": "From prior visit record: [00:00-00:04] Patient: Dizziness happened last month.",
                    },
                    {
                        "source_type": "current_result",
                        "chunk_id": "result-next-steps",
                        "visit_id": "job-current",
                        "quote": "Next steps: blood test | who: clinician | when: Not stated",
                    },
                ],
                "follow_up_suggestions": [
                    "Explain this simply.",
                    "What should I do first?",
                    "Help me prepare a follow-up question.",
                ],
                "safety_flag": False,
            }
        )

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-prior",
            transcript="[00:00-00:04] SPEAKER_0: Dizziness happened last month.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What changed since my last visit?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert any(source["source_type"] == "prior_visit" for source in payload["used_sources"])
    assert "From a prior visit record" in payload["answer"]


def test_same_chat_session_can_continue_after_job_is_attached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()
    call_count = {"value": 0}

    monkeypatch.setattr("medspeak.nvidia_nim.embed_texts", lambda **kwargs: [[0.2, 0.4, 0.6] for _ in kwargs["texts"]])
    monkeypatch.setattr("medspeak.nvidia_nim.rerank_indices", lambda **kwargs: list(range(min(kwargs["top_k"], len(kwargs["documents"])))))

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, temperature, max_tokens, messages
        call_count["value"] += 1
        return json.dumps(
            {
                "answer": "1. The visit discussed a blood test.\n2. The date was not stated.",
                "used_sources": [
                    {
                        "source_type": "current_result",
                        "chunk_id": "result-next-steps",
                        "visit_id": "job-current",
                        "quote": "Next steps: blood test | who: clinician | when: Not stated",
                    }
                ],
                "follow_up_suggestions": ["Explain this simply.", "What should I do first?", "Help me prepare a follow-up question."],
                "safety_flag": False,
            }
        )

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)

    with TestClient(create_app(settings)) as client:
        session_id = start_session(client)
        first = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "message": "How do I use this app?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        second = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What should I do first from this visit?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )
        history = client.get(f"/api/chat/history/{session_id}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["used_sources"][0]["source_type"] == "current_result"
    assert call_count["value"] == 0
    assert len(history.json()["messages"]) == 4


def test_chat_prompt_mentions_autism_mode_rules() -> None:
    prompt = chat_prompt.build_user_prompt(
        message="Explain this simply.",
        autism_mode=True,
        preferences=schema.Preferences(),
        recent_history=[],
        context_sources=[],
    )
    assert "Autism mode: ON" in prompt
    assert "If the context does not support the answer" in prompt
    assert "Website context explains the product workflow and interface only." in chat_prompt.SYSTEM_PROMPT


def test_fast_grounded_chat_answer_returns_without_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()
    call_count = {"value": 0}

    def fake_chat_completion(**kwargs: object) -> str:
        del kwargs
        call_count["value"] += 1
        raise AssertionError("LLM should not be called for fast next-step answers.")

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What should I do first?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("1. blood test. who: clinician. when: Not stated")
    assert payload["used_sources"][0]["chunk_id"] == "result-next-steps"
    assert call_count["value"] == 0


def test_chat_falls_back_to_grounded_source_when_nim_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()

    def failing_chat_completion(**kwargs: object) -> str:
        del kwargs
        raise NVIDIANIMError("NIM timed out.", retryable=True)

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", failing_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "Can you walk me through this visit?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "dizziness and a blood test" in payload["answer"].lower()
    assert payload["used_sources"][0]["chunk_id"] in {"result-standard-summary", "result-autism-summary"}


def test_chat_falls_back_when_json_repair_hits_degraded_nim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()
    call_count = {"value": 0}

    def flaky_chat_completion(**kwargs: object) -> str:
        del kwargs
        call_count["value"] += 1
        if call_count["value"] == 1:
            return "not valid json"
        raise NVIDIANIMError(
            'NVIDIA chat completion failed with status 400: {"status":400,"title":"Bad Request","detail":"Function id \'demo\': DEGRADED function cannot be invoked"}',
            retryable=True,
        )

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", flaky_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "What should I do first?",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("1. blood test. who: clinician. when: Not stated")
    assert payload["used_sources"][0]["chunk_id"] == "result-next-steps"


def test_realtime_chat_start_returns_immediate_final_for_workflow_question(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        session_id = start_session(client)
        response = client.post(
            "/api/chat/message/start",
            json={
                "chat_session_id": session_id,
                "message": "How do I use this app?",
                "autism_mode": True,
                "include_prior_visits": True,
                "ui_context": {
                    "page": "home",
                    "session_mode": "audio",
                    "status_message": "Ready.",
                    "has_audio_ready": False,
                    "job_status": None,
                    "active_result_tab": None,
                },
            },
        )
        history = client.get(f"/api/chat/history/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "final"
    assert payload["used_sources"][0]["source_type"] == "site_context"
    assert history.status_code == 200
    assistant = history.json()["messages"][-1]
    assert assistant["status"] == "final"
    assert assistant["message_id"] == payload["assistant_message_id"]
    assert assistant["updated_at"]


def test_realtime_chat_start_returns_draft_then_refines_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()

    def fake_chat_completion(*, settings: Settings, model: str, messages: list, temperature: float = 0.0, max_tokens: int = 0) -> str:
        del settings, model, messages, temperature, max_tokens
        time.sleep(0.1)
        return json.dumps(
            {
                "answer": "1. The visit discussed dizziness.\n2. A blood test was the recorded next step.\n3. Date not stated.",
                "used_sources": [
                    {
                        "source_type": "current_result",
                        "chunk_id": "result-standard-summary",
                        "visit_id": "job-current",
                        "quote": "Standard summary: The clinician discussed dizziness and a blood test.",
                    }
                ],
                "follow_up_suggestions": [
                    "Explain this simply.",
                    "What should I do first?",
                    "Help me prepare a follow-up question.",
                ],
                "safety_flag": False,
            }
        )

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", fake_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message/start",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "Give me a calmer overview of the discussion.",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

        assert response.status_code == 200
        started = response.json()
        assert started["status"] == "draft"

        finalized = wait_for_message_status(
            client,
            chat_session_id=session_id,
            message_id=started["assistant_message_id"],
            status="final",
        )

    assert finalized["message_id"] == started["assistant_message_id"]
    assert finalized["content"].startswith("1. The visit discussed dizziness.")
    assert finalized["delivery_note"] is None
    assert finalized["used_sources"][0]["chunk_id"] == "result-standard-summary"


def test_realtime_chat_finalizes_grounded_draft_when_nim_is_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    result = sample_result()

    def degraded_chat_completion(**kwargs: object) -> str:
        del kwargs
        raise NVIDIANIMError(
            'NVIDIA chat completion failed with status 400: {"status":400,"title":"Bad Request","detail":"Function id \'demo\': DEGRADED function cannot be invoked"}',
            retryable=True,
        )

    monkeypatch.setattr("medspeak.nvidia_nim.chat_completion", degraded_chat_completion)

    with TestClient(create_app(settings)) as client:
        seed_ready_job(
            client,
            job_id="job-current",
            transcript="[00:00-00:05] SPEAKER_0: I feel dizzy.\n[00:05-00:10] SPEAKER_1: We should do a blood test.",
            preferences=schema.Preferences().model_dump(),
            result=result,
        )
        session_id = start_session(client, "job-current")
        response = client.post(
            "/api/chat/message/start",
            json={
                "chat_session_id": session_id,
                "job_id": "job-current",
                "message": "Give me a calmer overview of the discussion.",
                "autism_mode": True,
                "include_prior_visits": True,
            },
        )

        assert response.status_code == 200
        started = response.json()
        assert started["status"] == "draft"

        finalized = wait_for_message_status(
            client,
            chat_session_id=session_id,
            message_id=started["assistant_message_id"],
            status="final",
        )

    assert finalized["content"]
    assert finalized["delivery_note"] == "Couldn't refine, showing grounded draft."
