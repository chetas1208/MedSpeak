from __future__ import annotations

import asyncio
import contextlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from medspeak import audio_utils, cache, llm_prompt, nvidia_nim, pii_redact, schema, smallest_stt, speaker_display
from medspeak.config import ConfigurationError, Settings, get_job_logger
from medspeak.jobs import JobStore
from medspeak.pdf_export import PDFGenerationError, generate_pdf_report
from medspeak.vector_store import VectorStore


PROGRESS_MAP: Dict[str, int] = {
    "QUEUED": 5,
    "NORMALIZE_AUDIO": 24,
    "TRANSCRIBE": 38,
    "REDACT": 50,
    "ANALYZE": 66,
    "VERIFY": 78,
    "INDEX": 90,
    "RENDER_PDF": 96,
    "READY": 100,
    "FAILED": 100,
}


class AgentWorker:
    def __init__(self, *, settings: Settings, job_store: JobStore, vector_store: VectorStore) -> None:
        self.settings = settings
        self.job_store = job_store
        self.vector_store = vector_store
        self.queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(settings.worker_concurrency)
        self._shutdown = asyncio.Event()
        self._runner_task: Optional["asyncio.Task[None]"] = None
        self._active_tasks: set = set()
        self.is_running = False
        self.ffmpeg_available = audio_utils.is_ffmpeg_available()

    async def start(self) -> None:
        self.is_running = True
        for job_id in self.job_store.list_recoverable_jobs():
            await self.queue.put(job_id)
        self._runner_task = asyncio.create_task(self._run_loop(), name="medspeak-worker")

    async def stop(self) -> None:
        self.is_running = False
        self._shutdown.set()
        if self._runner_task:
            self._runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner_task
        if self._active_tasks:
            for task in list(self._active_tasks):
                task.cancel()
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    def enqueue_nowait(self, job_id: str) -> None:
        self.queue.put_nowait(job_id)

    async def _run_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                job_id = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=self.settings.worker_poll_seconds,
                )
            except asyncio.TimeoutError:
                continue

            await self.semaphore.acquire()
            task = asyncio.create_task(self._process_job(job_id))
            self._active_tasks.add(task)
            task.add_done_callback(self._task_done)

    def _task_done(self, task: "asyncio.Task[None]") -> None:
        self.semaphore.release()
        self._active_tasks.discard(task)

    async def _process_job(self, job_id: str) -> None:
        await asyncio.to_thread(self._process_job_sync, job_id)

    def _process_job_sync(self, job_id: str) -> None:
        job = self.job_store.get_job(job_id)
        if not job or job.status in {"READY", "FAILED"}:
            return

        logger = get_job_logger(job_id)
        upload_path: Optional[Path] = None

        try:
            request_payload = json.loads(job.request_json)
            source_type = job.source_type
            transcript_source = ""
            conversation_id = job.conversation_id
            audio_hash = job.audio_hash
            source_hash = job.source_hash

            if source_type == "audio_upload":
                self.job_store.update_stage(job_id, "NORMALIZE_AUDIO", PROGRESS_MAP["NORMALIZE_AUDIO"])
                source_ref = json.loads(job.source_ref or "{}")
                upload_path = Path(source_ref["path"])
                audio_bytes = upload_path.read_bytes()
                normalized = audio_utils.normalize_audio_bytes(
                    audio_bytes=audio_bytes,
                    content_type=source_ref.get("content_type"),
                    filename=source_ref.get("filename"),
                    max_audio_seconds=self.settings.max_audio_seconds,
                )
                audio_hash = normalized.audio_hash
                cached_job = cache.find_cached_audio_job(self.job_store, audio_hash)
                if cached_job:
                    self.job_store.hydrate_from_cached(
                        target_job_id=job_id,
                        cached_job=cached_job,
                        audio_hash=audio_hash,
                    )
                    return
                self.job_store.update_stage(job_id, "TRANSCRIBE", PROGRESS_MAP["TRANSCRIBE"])
                transcript_source = smallest_stt.transcribe_wav(
                    wav_bytes=normalized.wav_bytes,
                    language=request_payload.get("language", "en"),
                    settings=self.settings,
                    logger=logger,
                ).transcript

            elif source_type == "transcript":
                transcript_source = str(request_payload["transcript"]).strip()
                source_hash = source_hash or cache.compute_transcript_hash(transcript_source)
            else:
                raise ConfigurationError("Unsupported source type '{0}'.".format(source_type))

            self.job_store.update_stage(job_id, "REDACT", PROGRESS_MAP["REDACT"])
            transcript_redacted = pii_redact.redact_transcript(
                transcript=transcript_source,
                settings=self.settings,
                logger=logger,
            )
            transcript_redacted, speaker_map = speaker_display.normalize_transcript_speakers(transcript_redacted)
            self.job_store.update_fields(
                job_id,
                transcript_original=transcript_source,
                transcript_redacted=transcript_redacted,
                audio_hash=audio_hash,
                source_hash=source_hash,
                conversation_id=conversation_id,
            )

            self.job_store.update_stage(job_id, "ANALYZE", PROGRESS_MAP["ANALYZE"])
            prior_context = self._safe_retrieve_context(job_id=job_id, transcript=transcript_redacted, logger=logger)
            prompt = llm_prompt.build_analysis_prompt(
                transcript=transcript_redacted,
                preferences=schema.Preferences.model_validate(request_payload["preferences"]),
                autism_mode=bool(request_payload.get("autism_mode", True)),
                language=str(request_payload.get("language", "en")),
                prior_context=prior_context,
            )
            result = self._generate_analysis(prompt=prompt, logger=logger)
            result = speaker_display.normalize_result_speakers(result, speaker_map)

            self.job_store.update_stage(job_id, "VERIFY", PROGRESS_MAP["VERIFY"])
            verified = self._verify_result(result=result, transcript=transcript_source)
            if self.settings.enable_qa_agent_llm:
                verified = self._optional_repair(prompt=prompt, result=verified, logger=logger)
            verified = speaker_display.normalize_result_speakers(verified, speaker_map)

            self.job_store.update_stage(job_id, "INDEX", PROGRESS_MAP["INDEX"])
            self._safe_index(job_id=job_id, conversation_id=conversation_id, transcript=transcript_redacted, logger=logger)

            self.job_store.update_stage(job_id, "RENDER_PDF", PROGRESS_MAP["RENDER_PDF"])
            pdf_path = generate_pdf_report(
                job_id=job_id,
                result=verified,
                transcript=transcript_redacted,
                output_dir=self.settings.pdf_dir,
                logger=logger,
            )

            self.job_store.mark_ready(
                job_id=job_id,
                audio_hash=audio_hash,
                source_hash=source_hash,
                conversation_id=conversation_id,
                transcript_original=transcript_source,
                transcript_redacted=transcript_redacted,
                result_json=verified.model_dump_json(),
                pdf_path=str(pdf_path),
            )
        except (
            ConfigurationError,
            audio_utils.AudioProcessingError,
            smallest_stt.SmallestSTTError,
            nvidia_nim.NVIDIANIMError,
            PDFGenerationError,
        ) as exc:
            self.job_store.mark_failed(job_id, str(exc))
        except Exception as exc:  # pragma: no cover
            self.job_store.mark_failed(job_id, "Unexpected worker failure: {0}".format(exc))
        finally:
            if upload_path and upload_path.exists():
                with contextlib.suppress(OSError):
                    upload_path.unlink()

    def _safe_retrieve_context(self, *, job_id: str, transcript: str, logger: Any) -> list:
        if not self.settings.use_qdrant:
            return []
        try:
            return self.vector_store.retrieve_context(query=transcript, exclude_job_id=job_id)
        except Exception as exc:  # pragma: no cover
            logger.info("Skipping retrieval context because vector search failed: %s", exc)
            return []

    def _safe_index(
        self,
        *,
        job_id: str,
        conversation_id: Optional[str],
        transcript: str,
        logger: Any,
    ) -> None:
        if not self.settings.use_qdrant:
            return
        try:
            self.vector_store.index_transcript(
                job_id=job_id,
                conversation_id=conversation_id,
                transcript=transcript,
            )
        except Exception as exc:  # pragma: no cover
            logger.info("Skipping transcript indexing because Qdrant indexing failed: %s", exc)

    def _generate_analysis(self, *, prompt: str, logger: Any) -> schema.AnalysisResult:
        primary = self._call_nim_chat(
            logger=logger,
            messages=[
                {"role": "system", "content": llm_prompt.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=3200,
        )
        try:
            return self._parse_result(primary)
        except Exception:
            repaired = self._call_nim_chat(
                logger=logger,
                messages=[
                    {"role": "system", "content": llm_prompt.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "{0}\n\n{1}\n\nPrevious response:\n{2}".format(
                            prompt,
                            llm_prompt.FIX_JSON_PROMPT,
                            primary,
                        ),
                    },
                ],
                max_tokens=3200,
            )
            return self._parse_result(repaired)

    def _call_nim_chat(self, *, logger: Any, messages: list[dict[str, str]], max_tokens: int) -> str:
        max_attempts = 2
        last_error: nvidia_nim.NVIDIANIMError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return nvidia_nim.chat_completion(
                    settings=self.settings,
                    model=self.settings.nim_llm_model,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                )
            except nvidia_nim.NVIDIANIMError as exc:
                last_error = exc
                if not exc.retryable or attempt >= max_attempts:
                    raise
                logger.info(
                    "Retrying NVIDIA chat completion after retryable response "
                    "(attempt %s/%s): %s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
        if last_error:
            raise last_error
        raise nvidia_nim.NVIDIANIMError("NVIDIA chat completion failed before any response was received.")

    def _parse_result(self, raw_text: str) -> schema.AnalysisResult:
        candidate = raw_text.strip()
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1:
                candidate = candidate[start : end + 1]
        payload = json.loads(candidate)
        normalized = schema.normalize_analysis_payload(payload)
        return schema.AnalysisResult.model_validate(normalized)

    def _optional_repair(self, *, prompt: str, result: schema.AnalysisResult, logger: Any) -> schema.AnalysisResult:
        repaired = self._call_nim_chat(
            logger=logger,
            messages=[
                {"role": "system", "content": llm_prompt.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Only remove unsupported facts or replace them with 'Not stated'. "
                        "Do not add any new facts. Return JSON only.\n\n"
                        "{0}\n\nCurrent JSON:\n{1}".format(prompt, result.model_dump_json())
                    ),
                },
            ],
            max_tokens=2600,
        )
        try:
            return self._parse_result(repaired)
        except Exception:
            return result

    def _verify_result(self, *, result: schema.AnalysisResult, transcript: str) -> schema.AnalysisResult:
        transcript_lower = re.sub(r"\s+", " ", transcript.lower())

        def grounded(value: str) -> bool:
            if value == schema.NOT_STATED:
                return True
            normalized = re.sub(r"[^a-z0-9\s]", " ", value.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if not normalized or len(normalized) < 3:
                return False
            return normalized in transcript_lower

        for item in result.next_steps_checklist:
            if not grounded(item.step):
                item.step = schema.NOT_STATED
            if not grounded(item.who):
                item.who = schema.NOT_STATED
            if not grounded(item.when):
                item.when = schema.NOT_STATED

        for item in result.medications:
            if not grounded(item.name):
                item.name = schema.NOT_STATED
            if not grounded(item.dose):
                item.dose = schema.NOT_STATED
            if not grounded(item.frequency):
                item.frequency = schema.NOT_STATED
            if not grounded(item.purpose):
                item.purpose = schema.NOT_STATED
            if not grounded(item.notes):
                item.notes = schema.NOT_STATED

        for item in result.tests_and_referrals:
            if not grounded(item.item):
                item.item = schema.NOT_STATED
            if not grounded(item.purpose):
                item.purpose = schema.NOT_STATED
            if not grounded(item.when):
                item.when = schema.NOT_STATED

        for segment in result.intent_timeline:
            if not grounded(segment.text):
                segment.text = schema.NOT_STATED
                segment.intents = ["OTHER"]
                segment.confidence = 0.0

        forbidden_phrases = [
            "you should",
            "you must",
            "start taking",
            "stop taking",
            "increase",
            "decrease",
        ]
        if any(phrase in result.standard_summary.lower() and phrase not in transcript_lower for phrase in forbidden_phrases):
            result.standard_summary = schema.NOT_STATED
        if any(
            phrase in result.autism_friendly_summary.lower() and phrase not in transcript_lower
            for phrase in forbidden_phrases
        ):
            result.autism_friendly_summary = schema.NOT_STATED

        if "This is for note-taking and clarity, not medical advice." not in result.safety_note:
            if result.safety_note == schema.NOT_STATED:
                result.safety_note = "This is for note-taking and clarity, not medical advice."
            else:
                result.safety_note = "{0} This is for note-taking and clarity, not medical advice.".format(
                    result.safety_note
                )
        return result
