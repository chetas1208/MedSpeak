from __future__ import annotations

from medspeak.chat_schema import ChatUIContext, RetrievedSource


SITE_CONTEXT_BLOCKS = [
    (
        "site-overview",
        "MedSpeak turns an uploaded or recorded medical visit into a transcript, structured summaries, intent views, next steps, accommodations, scripts, and a downloadable PDF report.",
    ),
    (
        "site-workflow",
        "The main workflow is: record locally or upload audio, choose autism mode and preferences, run analysis, wait for queued job stages, review results, and open the companion chat for grounded follow-up.",
    ),
    (
        "site-input-modes",
        "Audio workflow lets the user record in the browser or upload audio. Demo transcript mode lets the user load bundled sample text and analyze it without audio.",
    ),
    (
        "site-job-stages",
        "Background job stages are Queued, Normalizing Audio, Transcribing, Redacting, Analyzing, Verifying, Indexing, Rendering PDF, and Ready. The status rail explains where the job is in the pipeline.",
    ),
    (
        "site-navigation",
        "The website uses a top navbar with the MedSpeak logo on the left and theme plus GitHub controls on the right. A floating round logo opens the MedSpeak chat from the start of the session.",
    ),
    (
        "site-results-tabs",
        "Results tabs include summaries, intent view, next steps, accommodation card, social scripts, and transcript. The PDF download button exports the full visit report.",
    ),
    (
        "site-chat",
        "MedSpeak can answer workflow questions from the website context and visit questions only from the visit record. It shows evidence cards so the user can see the supporting source.",
    ),
    (
        "site-privacy",
        "The backend normalizes audio, transcribes with smallest.ai, redacts obvious PII, analyzes with NVIDIA NIM, and returns a redacted transcript plus structured visit outputs.",
    ),
]


def build_site_context_sources(*, ui_context: ChatUIContext) -> list[RetrievedSource]:
    sources = [
        RetrievedSource(
            source_type="site_context",
            visit_id="site",
            chunk_id=chunk_id,
            text=text,
            score=0.0,
        )
        for chunk_id, text in SITE_CONTEXT_BLOCKS
    ]
    sources.append(
        RetrievedSource(
            source_type="site_context",
            visit_id="ui",
            chunk_id="site-live-state",
            text=(
                f"Current page: {ui_context.page}. Session mode: {ui_context.session_mode}. "
                f"Status message: {ui_context.status_message}. Audio ready: {'yes' if ui_context.has_audio_ready else 'no'}. "
                f"Job status: {ui_context.job_status or 'Not stated'}. Active result tab: {ui_context.active_result_tab or 'Not stated'}."
            ),
            score=0.0,
        )
    )
    return sources
