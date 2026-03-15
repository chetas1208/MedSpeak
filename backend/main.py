from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from medspeak import cache, config, jobs, schema
from medspeak.agent_worker import AgentWorker
from medspeak.chat_realtime import ChatRealtimeManager
from medspeak.chat_schema import (
    ChatHistoryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatMessageStartResponse,
    ChatStartRequest,
    ChatStartResponse,
)
from medspeak.chat_service import ChatService
from medspeak.pdf_export import generate_pdf_report
from medspeak.speaker_display import normalize_result_speakers, normalize_transcript_speakers
from medspeak.vector_store import VectorStore


def _build_pdf_url(request: Request, settings: config.Settings, job: jobs.JobRecord) -> Optional[str]:
    if not job.pdf_path:
        return None
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/api/download/{job.job_id}.pdf"
    return str(request.url_for("download_pdf", job_id=job.job_id))


def _job_to_response(
    request: Request,
    settings: config.Settings,
    job: jobs.JobRecord,
) -> schema.JobResponse:
    display_transcript_source = job.transcript_redacted if job.transcript_redacted is not None else job.transcript_original
    display_transcript, speaker_map = normalize_transcript_speakers(display_transcript_source or "")
    result_json = None
    if job.result_json:
        result_json = normalize_result_speakers(schema.AnalysisResult.model_validate_json(job.result_json), speaker_map)

    return schema.JobResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        stage_times=job.stage_times,
        error=job.error,
        transcript_redacted=display_transcript or None,
        result_json=result_json,
        pdf_path_or_url=_build_pdf_url(request, settings, job),
    )


def _enqueue_job(
    *,
    app: FastAPI,
    source_type: str,
    request_payload: dict[str, object],
    source_ref: Optional[str] = None,
    conversation_id: Optional[str] = None,
    source_hash: Optional[str] = None,
) -> schema.JobEnqueueResponse:
    job_id = uuid4().hex
    job_store: jobs.JobStore = app.state.job_store
    worker: AgentWorker = app.state.worker

    job_store.create_job(
        job_id=job_id,
        source_type=source_type,
        request_payload=request_payload,
        source_ref=source_ref,
        conversation_id=conversation_id,
        source_hash=source_hash,
    )
    worker.enqueue_nowait(job_id)
    return schema.JobEnqueueResponse(job_id=job_id, status="QUEUED")


def create_app(settings: Optional[config.Settings] = None) -> FastAPI:
    resolved_settings = settings or config.get_settings()
    resolved_settings.data_dir.mkdir(parents=True, exist_ok=True)
    resolved_settings.upload_dir.mkdir(parents=True, exist_ok=True)
    resolved_settings.pdf_dir.mkdir(parents=True, exist_ok=True)
    config.configure_logging(resolved_settings.log_level)
    job_store = jobs.JobStore(resolved_settings.database_path)
    vector_store = VectorStore(resolved_settings)
    chat_realtime = ChatRealtimeManager()
    chat = ChatService(
        settings=resolved_settings,
        job_store=job_store,
        vector_store=vector_store,
        realtime_manager=chat_realtime,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker = AgentWorker(
            settings=resolved_settings,
            job_store=job_store,
            vector_store=vector_store,
        )
        app.state.worker = worker
        app.state.chat_realtime = chat_realtime
        config.get_job_logger("startup").info(
            "Starting MedSpeak backend with analysis model %s, chat model %s, Qdrant %s, ffmpeg %s",
            resolved_settings.nim_llm_model,
            resolved_settings.nim_chat_model,
            "enabled" if resolved_settings.use_qdrant else "disabled",
            "available" if worker.ffmpeg_available else "missing",
        )
        await chat_realtime.start()
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()
            await chat_realtime.stop()

    app = FastAPI(
        title="MedSpeak Backend",
        version="2.0.0",
        description="Queued voice medical conversation analyzer powered by smallest.ai and NVIDIA NIM.",
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.job_store = job_store
    app.state.vector_store = vector_store
    app.state.chat_service = chat
    app.state.chat_realtime = chat_realtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=schema.HealthResponse)
    def health() -> schema.HealthResponse:
        worker: AgentWorker = app.state.worker
        return schema.HealthResponse(
            status="ok",
            ffmpeg_available=worker.ffmpeg_available,
            use_qdrant=resolved_settings.use_qdrant,
            worker_running=worker.is_running,
        )

    @app.post("/api/analyze_from_audio", response_model=schema.JobEnqueueResponse)
    async def analyze_from_audio(
        request: Request,
        audio: UploadFile = File(...),
        payload: str = Form(...),
    ) -> schema.JobEnqueueResponse:
        try:
            parsed_payload = schema.AnalyzeFromAudioRequest.model_validate_json(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid audio payload: {exc}") from exc

        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

        upload_path = resolved_settings.upload_dir / f"{uuid4().hex}-{audio.filename or 'recording.webm'}"
        upload_path.write_bytes(audio_bytes)

        return _enqueue_job(
            app=app,
            source_type="audio_upload",
            request_payload=parsed_payload.model_dump(),
            source_ref=json.dumps(
                {
                    "path": str(upload_path),
                    "content_type": audio.content_type or "application/octet-stream",
                    "filename": audio.filename or upload_path.name,
                }
            ),
        )

    @app.post("/api/analyze_from_transcript", response_model=schema.JobEnqueueResponse)
    def analyze_from_transcript(
        payload: schema.AnalyzeFromTranscriptRequest,
        request: Request,
    ) -> schema.JobEnqueueResponse:
        source_hash = cache.compute_transcript_hash(payload.transcript)
        cached = cache.find_cached_transcript_job(app.state.job_store, source_hash)
        if cached:
            return schema.JobEnqueueResponse(job_id=cached.job_id, status=cached.status)

        return _enqueue_job(
            app=app,
            source_type="transcript",
            request_payload=payload.model_dump(),
            source_hash=source_hash,
        )

    @app.get("/api/job/{job_id}", response_model=schema.JobResponse)
    def get_job(job_id: str, request: Request) -> schema.JobResponse:
        job = app.state.job_store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return _job_to_response(request, resolved_settings, job)

    @app.post("/api/chat/start", response_model=ChatStartResponse)
    def start_chat(payload: ChatStartRequest) -> ChatStartResponse:
        chat_service: ChatService = app.state.chat_service
        return chat_service.start_session(job_id=payload.job_id)

    @app.post("/api/chat/message", response_model=ChatMessageResponse)
    def chat_message(payload: ChatMessageRequest) -> ChatMessageResponse:
        chat_service: ChatService = app.state.chat_service
        return chat_service.answer(payload)

    @app.post("/api/chat/message/start", response_model=ChatMessageStartResponse)
    def chat_message_start(payload: ChatMessageRequest) -> ChatMessageStartResponse:
        chat_service: ChatService = app.state.chat_service
        return chat_service.start_realtime_message(payload)

    @app.get("/api/chat/history/{chat_session_id}", response_model=ChatHistoryResponse)
    def chat_history(chat_session_id: str) -> ChatHistoryResponse:
        chat_service: ChatService = app.state.chat_service
        return chat_service.get_history(chat_session_id=chat_session_id)

    @app.get("/api/chat/stream/{chat_session_id}")
    async def chat_stream(chat_session_id: str) -> StreamingResponse:
        chat_service: ChatService = app.state.chat_service
        chat_service.get_history(chat_session_id=chat_session_id)
        realtime: ChatRealtimeManager = app.state.chat_realtime

        async def event_source() -> AsyncIterator[str]:
            async for event in realtime.subscribe(chat_session_id):
                if event is None:
                    yield ": ping\n\n"
                    continue
                payload = json.dumps(event.model_dump())
                yield f"event: {event.type}\n"
                yield f"data: {payload}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/download/{job_id}.pdf", name="download_pdf")
    def download_pdf(job_id: str) -> FileResponse:
        job = app.state.job_store.get_job(job_id)
        if not job or not job.pdf_path:
            raise HTTPException(status_code=404, detail="PDF not found.")
        pdf_path = Path(job.pdf_path)
        if job.result_json and (job.transcript_redacted or job.transcript_original):
            try:
                transcript_source = job.transcript_redacted if job.transcript_redacted is not None else job.transcript_original or ""
                transcript_display, speaker_map = normalize_transcript_speakers(transcript_source)
                result = normalize_result_speakers(schema.AnalysisResult.model_validate_json(job.result_json), speaker_map)
                pdf_path = generate_pdf_report(
                    job_id=job_id,
                    result=result,
                    transcript=transcript_display,
                    output_dir=resolved_settings.pdf_dir,
                    logger=config.get_job_logger(job_id),
                )
                if str(pdf_path) != job.pdf_path:
                    app.state.job_store.update_fields(job_id, pdf_path=str(pdf_path))
            except Exception:
                pdf_path = Path(job.pdf_path)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF not found.")
        return FileResponse(pdf_path, media_type="application/pdf", filename=f"{job_id}.pdf")

    return app


app = create_app()
