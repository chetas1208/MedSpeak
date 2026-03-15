from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


DEMO_TRANSCRIPT = """
[00:00-00:07] Patient: I have been tired and dizzy this week.
[00:07-00:15] Doctor: We can order a blood test and talk again after the results.
[00:15-00:20] Patient: Okay. What should I ask at the follow up?
""".strip()


def build_payload(transcript: str) -> dict:
    return {
        "transcript": transcript,
        "autism_mode": True,
        "preferences": {
            "communication_style": "Very explicit",
            "sensory": ["quiet_room", "explain_touch"],
            "processing": ["extra_time", "written_steps", "confirm_understanding"],
            "support": ["caregiver_allowed", "breaks_allowed"],
        },
        "language": "en",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a MedSpeak transcript smoke test.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    parser.add_argument("--timeout", type=float, default=45.0, help="Polling timeout in seconds.")
    parser.add_argument(
        "--transcript",
        default=DEMO_TRANSCRIPT,
        help="Transcript text to analyze. Defaults to a bundled demo transcript.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "{0}/api/analyze_from_transcript".format(base_url),
            json=build_payload(args.transcript),
        )
        response.raise_for_status()
        enqueue = response.json()
        job_id = enqueue["job_id"]
        print("Queued job:", json.dumps(enqueue, indent=2))

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            job_response = client.get("{0}/api/job/{1}".format(base_url, job_id))
            job_response.raise_for_status()
            job = job_response.json()
            print("Status:", job["status"], "Progress:", job["progress"])
            if job["status"] == "READY":
                print(json.dumps(job, indent=2))
                return 0
            if job["status"] == "FAILED":
                print(json.dumps(job, indent=2), file=sys.stderr)
                return 1
            time.sleep(1.0)

    print("Timed out waiting for the job to finish.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
