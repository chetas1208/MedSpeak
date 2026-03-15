# MedSpeak Frontend

Next.js frontend for MedSpeak.

## Features

- Record audio locally in the browser
- Upload an existing audio file for transcription
- Load a bundled demo transcript for judge testing
- Poll the backend worker and show live progress
- Render summaries, intent timeline, next steps, accommodation card, scripts, transcript, and PDF download
- Open MedSpeak in a floating grounded-chat drawer with evidence cards and follow-up prompts

## Setup

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

## Environment Variables

- `NEXT_PUBLIC_API_BASE_URL`: backend base URL, default `http://localhost:8000`

## Audio Flow

- Record locally, then upload the captured audio to `/api/analyze_from_audio`
- Or upload an existing file directly
- Or use `/api/analyze_from_transcript` through the built-in demo mode

## Grounded Chat

MedSpeak starts from page load. It answers only from:

- the current transcript
- the current structured result
- optional prior visits
- website context for workflow and interface questions

Unsupported questions fall back to:

`I can’t verify that from your visit record.`
