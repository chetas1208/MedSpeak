from __future__ import annotations

import json
from textwrap import dedent

from medspeak.chat_schema import RetrievedSource, UnsupportedAnswer
from medspeak.schema import Preferences


SYSTEM_PROMPT = dedent(
    f"""
    You are MedSpeak.
    You answer only from supplied grounded context.
    Never diagnose.
    Never provide new medical advice.
    Never recommend starting or stopping medication.
    If the answer is unsupported, ambiguous, or contradictory, reply exactly:
    "{UnsupportedAnswer}"
    If prior visit context is used, mention clearly that it is from a prior visit record.
    Website context explains the product workflow and interface only. It does not prove medical facts.
    Visit context includes current transcript, structured result, and prior visit records.
    When autism_mode=true:
    - use short literal sentences
    - avoid idioms
    - avoid vague timing words
    - use numbered steps where helpful
    - be explicit and calm
    Be friendly, direct, and calm.
    Return JSON only. No markdown. No extra text.
    JSON schema:
    {{
      "answer": "string",
      "used_sources": [
        {{"source_type":"current_transcript|current_result|prior_visit|site_context","chunk_id":"string","visit_id":"string","quote":"string"}}
      ],
      "follow_up_suggestions": ["string", "string", "string"],
      "safety_flag": false
    }}
    """
).strip()


FIX_JSON_PROMPT = "You returned invalid JSON. Fix it. Output ONLY valid JSON matching schema. Do not add keys."


def format_context(sources: list[RetrievedSource]) -> str:
    grouped: dict[str, list[RetrievedSource]] = {
        "current_transcript": [],
        "current_result": [],
        "prior_visit": [],
        "site_context": [],
    }
    for source in sources:
        grouped[source.source_type].append(source)

    sections: list[str] = []
    if grouped["current_transcript"]:
        sections.append("CURRENT VISIT TRANSCRIPT")
        sections.extend(
            f"- [{item.chunk_id}] (visit {item.visit_id}, score {item.score:.3f}) {item.text}"
            for item in grouped["current_transcript"]
        )
    if grouped["current_result"]:
        sections.append("CURRENT VISIT STRUCTURED RESULT")
        sections.extend(
            f"- [{item.chunk_id}] (visit {item.visit_id}, score {item.score:.3f}) {item.text}"
            for item in grouped["current_result"]
        )
    if grouped["prior_visit"]:
        sections.append("VISIT CONTEXT: PRIOR VISIT RECORDS (historical reference only)")
        sections.extend(
            f"- [{item.chunk_id}] (visit {item.visit_id}, score {item.score:.3f}) {item.text}"
            for item in grouped["prior_visit"]
        )
    if grouped["site_context"]:
        sections.append("WEBSITE CONTEXT")
        sections.extend(
            f"- [{item.chunk_id}] (visit {item.visit_id}, score {item.score:.3f}) {item.text}"
            for item in grouped["site_context"]
        )
    return "\n".join(sections) if sections else "No verified context was retrieved."


def build_user_prompt(
    *,
    message: str,
    autism_mode: bool,
    preferences: Preferences,
    recent_history: list[dict[str, str]],
    context_sources: list[RetrievedSource],
) -> str:
    history_block = "\n".join(f"{item['role'].upper()}: {item['content']}" for item in recent_history) or "Not stated"
    preferences_block = json.dumps(preferences.model_dump(), indent=2)
    context_block = format_context(context_sources)
    return dedent(
        f"""
        User question:
        {message}

        Autism mode: {"ON" if autism_mode else "OFF"}
        Communication preferences:
        {preferences_block}

        Recent chat history for continuity only:
        {history_block}

        Grounding context:
        {context_block}

        Rules:
        - Use only the provided grounding context.
        - Use WEBSITE CONTEXT only for workflow or interface help.
        - Use VISIT CONTEXT for anything about what happened in the visit, instructions, medications, tests, next steps, or comparisons.
        - Do not rely on unstated assumptions.
        - If the context does not support the answer, reply exactly "{UnsupportedAnswer}".
        - Keep answer quotes short and directly relevant.
        - Include exactly 3 follow_up_suggestions when possible.
        """
    ).strip()
