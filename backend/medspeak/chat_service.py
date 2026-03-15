from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from typing import Iterable, Optional

from fastapi import HTTPException

from medspeak import chat_prompt, nvidia_nim, schema, speaker_display
from medspeak.chat_memory import ChatMemoryService
from medspeak.chat_realtime import ChatRealtimeManager
from medspeak.chat_schema import (
    ChatHistoryResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatMessageStartResponse,
    ChatStartResponse,
    ChatStreamEvent,
    RetrievedSource,
    UnsupportedAnswer,
    UsedSource,
)
from medspeak.config import Settings
from medspeak.jobs import JobRecord, JobStore
from medspeak.site_context import build_site_context_sources
from medspeak.vector_store import VectorStore, chunk_text


UNSAFE_PATTERNS = (
    "diagnosis",
    "what illness",
    "what disease",
    "stop taking",
    "start taking",
    "change my medication",
)

VISIT_CONTEXT_PATTERNS = (
    "doctor",
    "clinician",
    "visit",
    "medication",
    "dose",
    "dosage",
    "symptom",
    "test",
    "lab",
    "referral",
    "blood test",
    "follow up",
    "question for next appointment",
    "red flag",
    "diagnosis",
    "illness",
    "disease",
    "what happened",
    "what did they say",
)


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        job_store: JobStore,
        vector_store: VectorStore,
        realtime_manager: ChatRealtimeManager,
    ) -> None:
        self.settings = settings
        self.job_store = job_store
        self.vector_store = vector_store
        self.realtime = realtime_manager
        self.memory = ChatMemoryService(job_store)
        self.logger = logging.getLogger("medspeak.chat")

    def start_session(self, *, job_id: str | None) -> ChatStartResponse:
        if job_id:
            self._require_existing_job(job_id)
        return self.memory.start_session(job_id=job_id)

    def get_history(self, *, chat_session_id: str) -> ChatHistoryResponse:
        try:
            return self.memory.get_history(chat_session_id=chat_session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def start_realtime_message(self, payload: ChatMessageRequest) -> ChatMessageStartResponse:
        context = self._prepare_message_context(payload)
        fast_response, should_refine = self._build_fast_first_response(
            message=payload.message,
            autism_mode=payload.autism_mode,
            context_sources=context["context_sources"],
        )
        status = "draft" if should_refine else "final"
        metadata = fast_response.model_dump()
        metadata["is_streaming_candidate"] = should_refine
        assistant_record = self.job_store.add_chat_message(
            chat_session_id=payload.chat_session_id,
            role="assistant",
            content=fast_response.answer,
            metadata=metadata,
            status=status,
        )
        self.realtime.publish(
            self._build_stream_event(
                event_type="draft_created" if should_refine else "message_finalized",
                chat_session_id=payload.chat_session_id,
                record=assistant_record,
            )
        )
        if should_refine:
            self.realtime.submit_refinement(
                assistant_record.message_id,
                lambda: self._refine_answer_async(
                    chat_session_id=payload.chat_session_id,
                    assistant_message_id=assistant_record.message_id,
                    message=payload.message,
                    autism_mode=payload.autism_mode,
                    preferences=context["preferences"],
                    recent_history=context["recent_history"],
                    context_sources=context["context_sources"],
                    draft_response=fast_response,
                ),
            )
        return ChatMessageStartResponse(
            assistant_message_id=assistant_record.message_id,
            status=status,
            answer=fast_response.answer,
            used_sources=fast_response.used_sources,
            follow_up_suggestions=fast_response.follow_up_suggestions,
            safety_flag=fast_response.safety_flag,
            delivery_note=fast_response.delivery_note,
        )

    def answer(self, payload: ChatMessageRequest) -> ChatMessageResponse:
        context = self._prepare_message_context(payload)
        current_visit_sources_present = any(
            source.source_type in {"current_transcript", "current_result"} for source in context["context_sources"]
        )
        if self._requires_visit_record(payload.message) and not current_visit_sources_present:
            response = self._fallback_response(message=payload.message, safety_flag=True)
            self.memory.append_assistant_message(
                chat_session_id=payload.chat_session_id,
                content=response.answer,
                metadata=response.model_dump(),
            )
            return response
        response = self._generate_grounded_answer(
            message=payload.message,
            autism_mode=payload.autism_mode,
            preferences=context["preferences"],
            recent_history=context["recent_history"],
            context_sources=context["context_sources"],
        )
        self.memory.append_assistant_message(
            chat_session_id=payload.chat_session_id,
            content=response.answer,
            metadata=response.model_dump(),
        )
        return response

    def _build_fast_first_response(
        self,
        *,
        message: str,
        autism_mode: bool,
        context_sources: list[RetrievedSource],
    ) -> tuple[ChatMessageResponse, bool]:
        if not context_sources:
            return self._fallback_response(message=message), False

        has_visit_sources = any(
            source.source_type in {"current_transcript", "current_result", "prior_visit"}
            for source in context_sources
        )
        if self._requires_visit_record(message) and not has_visit_sources:
            return self._fallback_response(message=message, safety_flag=True), False

        if all(source.source_type == "site_context" for source in context_sources):
            return self._site_context_fallback(context_sources=context_sources), False

        fast_response = self._fast_grounded_response(
            message=message,
            autism_mode=autism_mode,
            context_sources=context_sources,
        )
        if fast_response is not None:
            return fast_response, False

        draft_response = self._fallback_from_context(
            message=message,
            autism_mode=autism_mode,
            context_sources=context_sources,
        )
        if draft_response is None or draft_response.answer == UnsupportedAnswer:
            return self._fallback_response(message=message), False
        return draft_response, True

    async def _refine_answer_async(
        self,
        *,
        chat_session_id: str,
        assistant_message_id: int,
        message: str,
        autism_mode: bool,
        preferences: schema.Preferences,
        recent_history: list[dict[str, str]],
        context_sources: list[RetrievedSource],
        draft_response: ChatMessageResponse,
    ) -> None:
        refining_record = self.job_store.update_chat_message(
            message_id=assistant_message_id,
            status="refining",
            metadata=self._response_metadata(draft_response, is_streaming_candidate=True),
        )
        if refining_record is not None:
            self.realtime.publish(
                self._build_stream_event(
                    event_type="message_updated",
                    chat_session_id=chat_session_id,
                    record=refining_record,
                )
            )

        try:
            refined_response = await asyncio.to_thread(
                self._generate_model_answer,
                message=message,
                autism_mode=autism_mode,
                preferences=preferences,
                recent_history=recent_history,
                context_sources=context_sources,
            )
        except Exception as exc:
            self.logger.warning(
                "Finalizing MedSpeak draft after refinement failure for assistant message %s: %s",
                assistant_message_id,
                exc,
            )
            final_draft = ChatMessageResponse(
                answer=draft_response.answer,
                used_sources=draft_response.used_sources,
                follow_up_suggestions=draft_response.follow_up_suggestions,
                safety_flag=draft_response.safety_flag,
                delivery_note="Couldn't refine, showing grounded draft.",
            )
            finalized_record = self.job_store.update_chat_message(
                message_id=assistant_message_id,
                content=final_draft.answer,
                status="final",
                metadata=self._response_metadata(final_draft, is_streaming_candidate=False),
            )
            if finalized_record is not None:
                self.realtime.publish(
                    self._build_stream_event(
                        event_type="message_finalized",
                        chat_session_id=chat_session_id,
                        record=finalized_record,
                    )
                )
            return

        finalized_record = self.job_store.update_chat_message(
            message_id=assistant_message_id,
            content=refined_response.answer,
            status="final",
            metadata=self._response_metadata(refined_response, is_streaming_candidate=False),
        )
        if finalized_record is not None:
            self.realtime.publish(
                self._build_stream_event(
                    event_type="message_finalized",
                    chat_session_id=chat_session_id,
                    record=finalized_record,
                )
            )

    def _prepare_message_context(self, payload: ChatMessageRequest) -> dict[str, object]:
        session = self.job_store.get_chat_session(payload.chat_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found.")

        job = self._require_existing_job(payload.job_id) if payload.job_id else None
        if job and session.job_id != job.job_id:
            self.job_store.attach_chat_session_job(chat_session_id=payload.chat_session_id, job_id=job.job_id)
        preferences = self._extract_preferences(job) if job else schema.Preferences()
        self.memory.append_user_message(chat_session_id=payload.chat_session_id, content=payload.message)
        recent_history = self.memory.recent_history_for_prompt(chat_session_id=payload.chat_session_id, limit=6)
        context_sources = self._retrieve_context_sources(
            job=job,
            query=payload.message,
            include_prior_visits=payload.include_prior_visits,
            ui_context=payload.ui_context,
        )
        return {
            "job": job,
            "preferences": preferences,
            "recent_history": recent_history,
            "context_sources": context_sources,
        }

    def _require_existing_job(self, job_id: str) -> JobRecord:
        job = self.job_store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job

    def _extract_preferences(self, job: JobRecord | None) -> schema.Preferences:
        if not job:
            return schema.Preferences()
        try:
            payload = json.loads(job.request_json)
        except json.JSONDecodeError:
            return schema.Preferences()
        return schema.Preferences.model_validate(payload.get("preferences", {}))

    def _retrieve_context_sources(
        self,
        *,
        job: JobRecord | None,
        query: str,
        include_prior_visits: bool,
        ui_context,
    ) -> list[RetrievedSource]:
        sources = build_site_context_sources(ui_context=ui_context)
        if job:
            sources.extend(self._build_current_visit_sources(job))
        if include_prior_visits and job:
            sources.extend(self._build_prior_visit_sources(current_job_id=job.job_id))
            sources.extend(
                RetrievedSource.model_validate(item.__dict__)
                for item in self.vector_store.search_prior_chunks(query=query, exclude_job_id=job.job_id, top_k=4)
            )

        ranked = self._rank_sources(query=query, sources=sources, top_k=14)
        if not ranked:
            return []
        return ranked

    def _build_current_visit_sources(self, job: JobRecord) -> list[RetrievedSource]:
        transcript_source = (job.transcript_redacted or job.transcript_original or "").strip()
        transcript, speaker_map = speaker_display.normalize_transcript_speakers(transcript_source)
        sources: list[RetrievedSource] = []
        for index, chunk in enumerate(chunk_text(transcript)):
            sources.append(
                RetrievedSource(
                    source_type="current_transcript",
                    visit_id=job.job_id,
                    chunk_id=f"current-transcript-{index}",
                    text=chunk,
                    score=0.0,
                )
            )

        if job.result_json:
            try:
                result = schema.AnalysisResult.model_validate_json(job.result_json)
            except Exception:
                result = None
            if result:
                result = speaker_display.normalize_result_speakers(result, speaker_map)
                for chunk_id, text in self._result_blocks(result):
                    sources.append(
                        RetrievedSource(
                            source_type="current_result",
                            visit_id=job.job_id,
                            chunk_id=chunk_id,
                            text=text,
                            score=0.0,
                        )
                    )
        return sources

    def _build_prior_visit_sources(self, *, current_job_id: str) -> list[RetrievedSource]:
        sources: list[RetrievedSource] = []
        for job in self.job_store.list_ready_jobs(exclude_job_id=current_job_id, limit=6):
            transcript_source = (job.transcript_redacted or job.transcript_original or "").strip()
            transcript, speaker_map = speaker_display.normalize_transcript_speakers(transcript_source)
            for index, chunk in enumerate(chunk_text(transcript)[:2]):
                sources.append(
                    RetrievedSource(
                        source_type="prior_visit",
                        visit_id=job.job_id,
                        chunk_id=f"prior-transcript-{job.job_id}-{index}",
                        text=f"From prior visit record: {chunk}",
                        score=0.0,
                    )
                )
            if job.result_json:
                try:
                    result = schema.AnalysisResult.model_validate_json(job.result_json)
                except Exception:
                    result = None
                if result:
                    result = speaker_display.normalize_result_speakers(result, speaker_map)
                    for chunk_id, text in self._result_blocks(result)[:3]:
                        sources.append(
                            RetrievedSource(
                                source_type="prior_visit",
                                visit_id=job.job_id,
                                chunk_id=f"prior-result-{job.job_id}-{chunk_id}",
                                text=f"From prior visit record: {text}",
                                score=0.0,
                            )
                        )
        return sources

    def _result_blocks(self, result: schema.AnalysisResult) -> list[tuple[str, str]]:
        next_steps = "; ".join(
            f"{item.step} | who: {item.who} | when: {item.when}" for item in result.next_steps_checklist
        )
        meds = "; ".join(
            f"{item.name} | dose: {item.dose} | frequency: {item.frequency} | purpose: {item.purpose}"
            for item in result.medications
        )
        tests = "; ".join(
            f"{item.item} | purpose: {item.purpose} | when: {item.when}" for item in result.tests_and_referrals
        )
        intent_summary = "; ".join(result.intent_summary)
        questions = "; ".join(result.questions_to_ask)
        accommodations = "; ".join(
            [
                result.accommodation_card.summary,
                f"Communication: {', '.join(result.accommodation_card.communication)}",
                f"Sensory: {', '.join(result.accommodation_card.sensory)}",
                f"Processing: {', '.join(result.accommodation_card.processing)}",
                f"Support: {', '.join(result.accommodation_card.support)}",
            ]
        )
        scripts = "; ".join(f"{item.situation}: {item.script}" for item in result.social_scripts)
        return [
            ("result-standard-summary", f"Standard summary: {result.standard_summary}"),
            ("result-autism-summary", f"Autism-friendly summary: {result.autism_friendly_summary}"),
            ("result-next-steps", f"Next steps: {next_steps}"),
            ("result-medications", f"Medications: {meds}"),
            ("result-tests", f"Tests and referrals: {tests}"),
            ("result-intent-summary", f"Intent summary: {intent_summary}"),
            ("result-questions", f"Questions to ask: {questions}"),
            ("result-accommodations", f"Accommodation card: {accommodations}"),
            ("result-scripts", f"Social scripts: {scripts}"),
            ("result-safety", f"Safety note: {result.safety_note}"),
        ]

    def _rank_sources(self, *, query: str, sources: list[RetrievedSource], top_k: int) -> list[RetrievedSource]:
        unique: dict[tuple[str, str, str], RetrievedSource] = {}
        for source in sources:
            key = (source.source_type, source.visit_id, source.chunk_id)
            if key not in unique and source.text.strip():
                unique[key] = source
        candidates = list(unique.values())
        if not candidates:
            return []

        for source in candidates:
            score = self._keyword_score(query, source.text)
            score += self._source_priority_bonus(source.source_type)
            score += min(source.score, 1.0) * 0.1
            if source.visit_id == "ui":
                score += 0.04
            source.score = score

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:top_k]

    def _generate_grounded_answer(
        self,
        *,
        message: str,
        autism_mode: bool,
        preferences: schema.Preferences,
        recent_history: list[dict[str, str]],
        context_sources: list[RetrievedSource],
    ) -> ChatMessageResponse:
        if not context_sources:
            return self._fallback_response(message=message)
        if all(source.source_type == "site_context" for source in context_sources):
            return self._site_context_fallback(context_sources=context_sources)
        fast_response = self._fast_grounded_response(
            message=message,
            autism_mode=autism_mode,
            context_sources=context_sources,
        )
        if fast_response is not None:
            return fast_response

        try:
            return self._generate_model_answer(
                message=message,
                autism_mode=autism_mode,
                preferences=preferences,
                recent_history=recent_history,
                context_sources=context_sources,
            )
        except nvidia_nim.NVIDIANIMError as exc:
            self.logger.warning("Falling back to fast grounded MedSpeak answer after NVIDIA error: %s", exc)
            fallback = self._fallback_from_context(
                message=message,
                autism_mode=autism_mode,
                context_sources=context_sources,
            )
            if fallback is not None:
                return fallback
            if all(source.source_type == "site_context" for source in context_sources):
                return self._site_context_fallback(context_sources=context_sources)
            raise
        except Exception:
            fallback = self._fallback_from_context(
                message=message,
                autism_mode=autism_mode,
                context_sources=context_sources,
            )
            if fallback is not None:
                return fallback
            return self._fallback_response(message=message)

    def _generate_model_answer(
        self,
        *,
        message: str,
        autism_mode: bool,
        preferences: schema.Preferences,
        recent_history: list[dict[str, str]],
        context_sources: list[RetrievedSource],
    ) -> ChatMessageResponse:

        prompt = chat_prompt.build_user_prompt(
            message=message,
            autism_mode=autism_mode,
            preferences=preferences,
            recent_history=recent_history,
            context_sources=context_sources,
        )
        try:
            primary = self._call_nim_chat(
                messages=[
                    {"role": "system", "content": chat_prompt.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
            )
        except nvidia_nim.NVIDIANIMError:
            raise
        try:
            return self._parse_response(message=message, raw=primary, context_sources=context_sources)
        except Exception:
            repaired = self._call_nim_chat(
                messages=[
                    {"role": "system", "content": chat_prompt.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"{prompt}\n\n{chat_prompt.FIX_JSON_PROMPT}\n\nPrevious response:\n{primary}",
                    },
                ],
                max_tokens=1400,
            )
            return self._parse_response(message=message, raw=repaired, context_sources=context_sources)

    def _fast_grounded_response(
        self,
        *,
        message: str,
        autism_mode: bool,
        context_sources: list[RetrievedSource],
    ) -> ChatMessageResponse | None:
        lowered = message.lower()
        if self._requires_visit_record(message) and not any(
            source.source_type in {"current_transcript", "current_result", "prior_visit"} for source in context_sources
        ):
            return self._fallback_response(message=message, safety_flag=True)

        current_results = {
            source.chunk_id: source for source in context_sources if source.source_type == "current_result"
        }
        prior_sources = [source for source in context_sources if source.source_type == "prior_visit"]
        transcript_sources = [source for source in context_sources if source.source_type == "current_transcript"]

        if "what should i do first" in lowered or "next step" in lowered or "what do i do first" in lowered:
            source = current_results.get("result-next-steps") or current_results.get("result-autism-summary")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=autism_mode,
                follow_ups=["Explain this simply.", "What did they say about medication?", "Help me prepare a follow-up question."],
            )

        if "medication" in lowered or "dose" in lowered or "dosage" in lowered:
            source = current_results.get("result-medications")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=autism_mode,
                follow_ups=["Explain this simply.", "Turn this into 3 steps.", "Help me prepare a follow-up question."],
            )

        if "explain this simply" in lowered or ("explain" in lowered and "simple" in lowered):
            source = current_results.get("result-autism-summary") or current_results.get("result-standard-summary")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=True,
                follow_ups=["What should I do first?", "Turn this into 3 steps.", "Help me prepare a follow-up question."],
            )

        if "turn this into 3 steps" in lowered or "3 steps" in lowered:
            source = current_results.get("result-next-steps") or current_results.get("result-autism-summary")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=True,
                force_numbered=True,
                follow_ups=["Explain this simply.", "What should I do first?", "Help me prepare a follow-up question."],
            )

        if "help me prepare a follow-up question" in lowered or "question to ask" in lowered:
            source = current_results.get("result-questions") or current_results.get("result-scripts")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=autism_mode,
                force_numbered=True,
                follow_ups=["What should I do first?", "Explain this simply.", "What changed since my last visit?"],
            )

        if "what changed since my last visit" in lowered or ("changed" in lowered and "last visit" in lowered):
            current = current_results.get("result-standard-summary") or current_results.get("result-autism-summary")
            prior = prior_sources[0] if prior_sources else None
            if current and prior and not self._contains_not_stated(current.text):
                answer = (
                    "1. From a prior visit record: "
                    f"{self._summarize_source_text(prior.text)}\n"
                    "2. In this visit: "
                    f"{self._summarize_source_text(current.text)}"
                )
                return ChatMessageResponse(
                    answer=answer,
                    used_sources=[self._used_source(prior), self._used_source(current)],
                    follow_up_suggestions=[
                        "Explain this simply.",
                        "What should I do first?",
                        "Help me prepare a follow-up question.",
                    ],
                    safety_flag=False,
                )

        if "what happened" in lowered or "summarize my visit" in lowered:
            source = current_results.get("result-standard-summary") or current_results.get("result-autism-summary")
            return self._build_response_from_source(
                message=message,
                source=source,
                autism_mode=autism_mode,
                follow_ups=["Explain this simply.", "What should I do first?", "What did they say about medication?"],
            )

        if transcript_sources and len(context_sources) <= 4:
            return self._build_response_from_source(
                message=message,
                source=transcript_sources[0],
                autism_mode=autism_mode,
                follow_ups=self._default_suggestions(),
            )
        return None

    def _fallback_from_context(
        self,
        *,
        message: str,
        autism_mode: bool,
        context_sources: list[RetrievedSource],
    ) -> ChatMessageResponse | None:
        non_site_sources = [source for source in context_sources if source.source_type != "site_context"]
        if not non_site_sources:
            return self._site_context_fallback(context_sources=context_sources)
        preferred = self._select_preferred_source(message=message, context_sources=non_site_sources)
        return self._build_response_from_source(
            message=message,
            source=preferred,
            autism_mode=autism_mode,
            follow_ups=self._default_suggestions(),
        )

    def _select_preferred_source(
        self,
        *,
        message: str,
        context_sources: list[RetrievedSource],
    ) -> RetrievedSource:
        lowered = message.lower()
        current_results = {
            source.chunk_id: source for source in context_sources if source.source_type == "current_result"
        }
        current_transcripts = [source for source in context_sources if source.source_type == "current_transcript"]
        prior_sources = [source for source in context_sources if source.source_type == "prior_visit"]

        if "medication" in lowered or "dose" in lowered or "dosage" in lowered:
            return current_results.get("result-medications") or current_transcripts[0] if current_transcripts else context_sources[0]
        if "question" in lowered:
            return current_results.get("result-questions") or current_results.get("result-scripts") or (
                current_transcripts[0] if current_transcripts else context_sources[0]
            )
        if "changed" in lowered and "visit" in lowered and prior_sources:
            return prior_sources[0]
        if "what happened" in lowered or "visit" in lowered or "explain" in lowered:
            return current_results.get("result-standard-summary") or current_results.get("result-autism-summary") or (
                current_transcripts[0] if current_transcripts else context_sources[0]
            )
        if "first" in lowered or "next step" in lowered:
            return current_results.get("result-next-steps") or current_results.get("result-autism-summary") or (
                current_transcripts[0] if current_transcripts else context_sources[0]
            )
        return current_transcripts[0] if current_transcripts else context_sources[0]

    def _build_response_from_source(
        self,
        *,
        message: str,
        source: RetrievedSource | None,
        autism_mode: bool,
        follow_ups: list[str],
        force_numbered: bool = False,
    ) -> ChatMessageResponse | None:
        if source is None or self._contains_not_stated(source.text):
            return self._fallback_response(message=message, safety_flag=any(pattern in message.lower() for pattern in UNSAFE_PATTERNS))

        answer = self._format_source_answer(
            source=source,
            autism_mode=autism_mode,
            force_numbered=force_numbered,
        )
        if not answer:
            return self._fallback_response(message=message, safety_flag=any(pattern in message.lower() for pattern in UNSAFE_PATTERNS))

        return ChatMessageResponse(
            answer=answer,
            used_sources=[self._used_source(source)],
            follow_up_suggestions=follow_ups[:3],
            safety_flag=any(pattern in message.lower() for pattern in UNSAFE_PATTERNS),
        )

    def _format_source_answer(
        self,
        *,
        source: RetrievedSource,
        autism_mode: bool,
        force_numbered: bool,
    ) -> str:
        parts = self._split_source_parts(source.text)
        if not parts:
            return ""
        if source.source_type == "prior_visit":
            parts[0] = f"From a prior visit record: {parts[0]}"
        if force_numbered or autism_mode or len(parts) > 1:
            return "\n".join(f"{index + 1}. {part}" for index, part in enumerate(parts[:3]))
        return parts[0]

    def _split_source_parts(self, text: str) -> list[str]:
        summary = self._summarize_source_text(text)
        if not summary or summary == "Not stated":
            return []
        if "\n" in summary:
            items = [line.strip(" -") for line in summary.splitlines() if line.strip()]
        elif "; " in summary:
            items = [item.strip() for item in summary.split("; ") if item.strip()]
        else:
            items = [summary.strip()]
        normalized = [item.replace(" | ", ". ").strip() for item in items if item.strip()]
        return normalized[:3]

    def _summarize_source_text(self, text: str) -> str:
        cleaned = text.strip()
        if ": " in cleaned:
            prefix, rest = cleaned.split(": ", 1)
            if prefix.lower() in {
                "standard summary",
                "autism-friendly summary",
                "next steps",
                "medications",
                "tests and referrals",
                "intent summary",
                "questions to ask",
                "accommodation card",
                "social scripts",
                "safety note",
            }:
                cleaned = rest.strip()
        return cleaned

    def _contains_not_stated(self, text: str) -> bool:
        lowered = text.lower()
        return lowered == "not stated" or "not stated" in lowered and all(
            token in lowered for token in ("dose", "frequency")
        )

    def _used_source(self, source: RetrievedSource) -> UsedSource:
        return UsedSource(
            source_type=source.source_type,
            visit_id=source.visit_id,
            chunk_id=source.chunk_id,
            quote=source.text[:180].strip(),
        )

    def _response_metadata(self, response: ChatMessageResponse, *, is_streaming_candidate: bool) -> dict[str, object]:
        metadata = response.model_dump()
        metadata["is_streaming_candidate"] = is_streaming_candidate
        return metadata

    def _build_stream_event(
        self,
        *,
        event_type: ChatStreamEvent["type"],
        chat_session_id: str,
        record,
    ) -> ChatStreamEvent:
        metadata = record.metadata or {}
        used_sources = [UsedSource.model_validate(item) for item in metadata.get("used_sources", [])]
        suggestions = [str(item) for item in metadata.get("follow_up_suggestions", [])][:3]
        return ChatStreamEvent(
            type=event_type,
            chat_session_id=chat_session_id,
            message_id=record.message_id,
            status=record.status,  # type: ignore[arg-type]
            answer=record.content,
            used_sources=used_sources,
            follow_up_suggestions=suggestions,
            safety_flag=bool(metadata.get("safety_flag", False)),
            delivery_note=metadata.get("delivery_note"),
        )

    def _call_nim_chat(self, *, messages: list[dict[str, str]], max_tokens: int) -> str:
        max_attempts = 2
        last_error: nvidia_nim.NVIDIANIMError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return nvidia_nim.chat_completion(
                    settings=self.settings,
                    model=self.settings.nim_chat_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
            except nvidia_nim.NVIDIANIMError as exc:
                last_error = exc
                if not exc.retryable or attempt >= max_attempts:
                    raise
                self.logger.info(
                    "Retrying NVIDIA MedSpeak completion after retryable response "
                    "(attempt %s/%s): %s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
        if last_error:
            raise last_error
        raise nvidia_nim.NVIDIANIMError("NVIDIA MedSpeak completion failed before any response was received.")

    def _parse_response(
        self,
        *,
        message: str,
        raw: str,
        context_sources: list[RetrievedSource],
    ) -> ChatMessageResponse:
        candidate = raw.strip()
        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1:
                candidate = candidate[start : end + 1]
        payload = json.loads(candidate)
        source_lookup = {
            (source.source_type, source.visit_id, source.chunk_id): source for source in context_sources
        }

        normalized_sources: list[UsedSource] = []
        for item in payload.get("used_sources", []):
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("source_type", "")),
                str(item.get("visit_id", "")),
                str(item.get("chunk_id", "")),
            )
            source = source_lookup.get(key)
            if not source:
                continue
            quote = str(item.get("quote", "")).strip()
            if not quote or quote not in source.text:
                quote = source.text[:180].strip()
            normalized_sources.append(
                UsedSource(
                    source_type=source.source_type,  # type: ignore[arg-type]
                    visit_id=source.visit_id,
                    chunk_id=source.chunk_id,
                    quote=quote,
                )
            )

        answer = str(payload.get("answer", "")).strip() or UnsupportedAnswer
        suggestions = payload.get("follow_up_suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = []
        cleaned_suggestions = [str(item).strip() for item in suggestions if str(item).strip()][:3]

        safety_flag = bool(payload.get("safety_flag", False)) or any(
            pattern in message.lower() for pattern in UNSAFE_PATTERNS
        )
        if answer != UnsupportedAnswer and not normalized_sources:
            return self._fallback_response(message=message, safety_flag=safety_flag)
        if answer != UnsupportedAnswer and self._requires_visit_record(message):
            if not any(source.source_type != "site_context" for source in normalized_sources):
                return self._fallback_response(message=message, safety_flag=True)
        if UnsupportedAnswer in answer and answer != UnsupportedAnswer:
            answer = UnsupportedAnswer
        response = ChatMessageResponse(
            answer=answer,
            used_sources=normalized_sources,
            follow_up_suggestions=cleaned_suggestions or self._default_suggestions(),
            safety_flag=safety_flag,
        )
        if response.answer == UnsupportedAnswer:
            response.used_sources = []
        return response

    def _fallback_response(self, *, message: str, safety_flag: Optional[bool] = None) -> ChatMessageResponse:
        flag = safety_flag if safety_flag is not None else any(pattern in message.lower() for pattern in UNSAFE_PATTERNS)
        return ChatMessageResponse(
            answer=UnsupportedAnswer,
            used_sources=[],
            follow_up_suggestions=self._default_suggestions(),
            safety_flag=flag,
        )

    def _default_suggestions(self) -> list[str]:
        return [
            "What should I do first?",
            "Explain this simply.",
            "Help me prepare a follow-up question.",
        ]

    def _site_context_fallback(self, *, context_sources: list[RetrievedSource]) -> ChatMessageResponse:
        prioritized = [source for source in context_sources if source.chunk_id in {"site-workflow", "site-job-stages", "site-results-tabs"}]
        used_sources = [
            UsedSource(
                source_type=source.source_type,
                visit_id=source.visit_id,
                chunk_id=source.chunk_id,
                quote=source.text[:180].strip(),
            )
            for source in prioritized[:2]
        ]
        return ChatMessageResponse(
            answer=(
                "1. Record locally or upload audio.\n"
                "2. Choose your preferences and run analysis.\n"
                "3. Wait for the job to finish, then review the visit report and PDF."
            ),
            used_sources=used_sources,
            follow_up_suggestions=[
                "What does the job status mean?",
                "How do I upload audio?",
                "When can I download the PDF?",
            ],
            safety_flag=False,
        )

    def _requires_visit_record(self, message: str) -> bool:
        lowered = message.lower()
        return any(pattern in lowered for pattern in VISIT_CONTEXT_PATTERNS)

    def _keyword_score(self, query: str, text: str) -> float:
        query_terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
        if not query_terms:
            return 0.0
        text_terms = set(re.findall(r"[a-z0-9]+", text.lower()))
        return len(query_terms & text_terms) / len(query_terms)

    def _source_priority_bonus(self, source_type: str) -> float:
        if source_type == "current_transcript":
            return 0.35
        if source_type == "current_result":
            return 0.24
        if source_type == "prior_visit":
            return 0.12
        return 0.08

    def _cosine_similarity(self, left: Iterable[float], right: Iterable[float]) -> float:
        left_values = list(left)
        right_values = list(right)
        if not left_values or not right_values or len(left_values) != len(right_values):
            return 0.0
        numerator = sum(a * b for a, b in zip(left_values, right_values))
        left_norm = math.sqrt(sum(a * a for a in left_values))
        right_norm = math.sqrt(sum(b * b for b in right_values))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)
