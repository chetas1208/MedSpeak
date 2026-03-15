from __future__ import annotations

import json
from textwrap import dedent

from medspeak.schema import Preferences


INTENT_LABELS = [
    "SYMPTOMS",
    "MEDICAL_HISTORY",
    "MEDICATION_INSTRUCTION",
    "TEST_OR_LAB_ORDER",
    "REFERRAL",
    "FOLLOW_UP_PLAN",
    "RED_FLAGS_WARNING",
    "LIFESTYLE_GUIDANCE",
    "ADMIN_LOGISTICS",
    "CLARIFICATION_QUESTION",
    "OTHER",
]


SYSTEM_PROMPT = dedent(
    """
    You are MedSpeak, a medical conversation analyzer.
    Use ONLY the transcript and clearly-labeled prior-visit context if it is provided.
    Never invent facts. Never invent diagnoses, medications, dosages, test results, or timelines.
    Never provide medical advice or diagnosis.
    If something is not stated, output exactly "Not stated".
    Return JSON only. No markdown. No extra text.
    Autism-friendly summary rules:
    - short sentences
    - no idioms
    - numbered steps for actions
    - if timing is unknown, write "Date not stated"
    - briefly explain medical terms only if they already appear in the transcript
    Safety note must include: "This is for note-taking and clarity, not medical advice."
    """
).strip()


FIX_JSON_PROMPT = "You returned invalid JSON. Fix it. Output ONLY valid JSON matching schema. Do not add keys."


SCHEMA_INSTRUCTION = dedent(
    """
    JSON schema:
    {
      "standard_summary": "string",
      "autism_friendly_summary": "string",
      "intent_summary": ["string"],
      "intent_timeline": [
        {"start":"string","end":"string","speaker":"string","text":"string","intents":["string"],"confidence":0.0}
      ],
      "next_steps_checklist": [{"step":"string","who":"string","when":"string"}],
      "medications": [{"name":"string","dose":"string","frequency":"string","purpose":"string","notes":"string"}],
      "tests_and_referrals": [{"item":"string","purpose":"string","when":"string"}],
      "red_flags": ["string"],
      "questions_to_ask": ["string"],
      "accommodation_card": {
        "summary":"string",
        "communication":["string"],
        "sensory":["string"],
        "processing":["string"],
        "support":["string"]
      },
      "social_scripts": [{"situation":"string","script":"string"}],
      "uncertainties": ["string"],
      "safety_note": "string"
    }
    Intent labels:
    ["SYMPTOMS","MEDICAL_HISTORY","MEDICATION_INSTRUCTION","TEST_OR_LAB_ORDER","REFERRAL","FOLLOW_UP_PLAN","RED_FLAGS_WARNING","LIFESTYLE_GUIDANCE","ADMIN_LOGISTICS","CLARIFICATION_QUESTION","OTHER"]
    """
).strip()


def build_analysis_prompt(
    *,
    transcript: str,
    preferences: Preferences,
    autism_mode: bool,
    language: str,
    prior_context: list[str],
) -> str:
    preference_payload = json.dumps(preferences.model_dump(), indent=2)
    context_block = "\n".join(f"- From prior visit record: {item}" for item in prior_context) or "Not stated"
    return dedent(
        f"""
        Analyze the transcript and return strict JSON.

        Autism mode: {"ON" if autism_mode else "OFF"}
        Language: {language}
        Preferences:
        {preference_payload}

        PAST CONTEXT (for reference only, from prior visit record):
        {context_block}

        Rules:
        - Use current transcript as the source of current facts.
        - Past context must only be described as prior-visit context.
        - If something is not stated, output "Not stated".
        - Do not invent medical advice, diagnoses, medications, tests, or timing.
        - intent_timeline should follow the transcript order.
        - confidence must be between 0 and 1.

        {SCHEMA_INSTRUCTION}

        Transcript:
        {transcript}
        """
    ).strip()
