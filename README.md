# MedSpeak

MedSpeak is a voice medical-visit companion. It takes a recorded visit, transcribes it, turns it into structured notes, produces an autism-friendly summary, generates a polished PDF, and lets the user ask grounded follow-up questions through a chat interface.

The project is built as a local full-stack app:

- `frontend/`: Next.js + TypeScript UI
- `backend/`: FastAPI API + background worker + SQLite storage

## What MedSpeak Does

MedSpeak is designed for after-visit clarity, not for diagnosis and not for medical advice.

The app:

- accepts a local audio recording or uploaded audio file
- converts audio to a normalized WAV format with `ffmpeg`
- transcribes the visit with `smallest.ai Pulse`
- redacts contact-style PII before model analysis
- extracts structured visit outputs with NVIDIA NIM models
- generates a branded PDF report
- stores results locally in SQLite
- offers a grounded chatbot that answers only from:
  - the current visit transcript
  - the current structured result
  - prior stored visit context
  - visible app/workflow context

If the answer is not supported by the stored evidence, MedSpeak falls back instead of inventing facts.

## Tools and Services Used

This section is intentionally precise about what is actually used in this repository.

### 1. smallest.ai

Used directly in the backend for speech-to-text.

- Service: `smallest.ai Pulse`
- Endpoint:
  `POST https://waves-api.smallest.ai/api/v1/pulse/get_text`
- Purpose:
  transcribe uploaded medical-visit audio
- Features used:
  - diarization
  - word timestamps
  - English or multilingual mode

Where it is used:

- [backend/medspeak/smallest_stt.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/smallest_stt.py)
- [backend/medspeak/agent_worker.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/agent_worker.py)

### 2. NVIDIA NIM Models

Used directly in the backend for analysis, grounded chat, embeddings, reranking, and PII entity extraction.

Main models currently configured in code:

- Analysis model:
  `nvidia/llama-3.3-nemotron-super-49b-v1.5`
- Chat model:
  `nvidia/llama-3.1-nemotron-nano-8b-v1`
- Embedding model:
  `nvidia/llama-nemotron-embed-1b-v2`
- Reranker:
  `nvidia/llama-nemotron-rerank-1b-v2`
- PII model:
  `nvidia/gliner-pii`

Endpoints used:

- Chat completions:
  `POST https://integrate.api.nvidia.com/v1/chat/completions`
- Embeddings:
  `POST https://integrate.api.nvidia.com/v1/embeddings`
- Reranking:
  `POST https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-1b-v2/reranking`

Purpose of each model:

- Analysis model:
  convert the transcript into strict structured JSON for summaries, intent timeline, next steps, medications, tests/referrals, questions, accommodation card, and social scripts
- Chat model:
  answer grounded user questions in the MedSpeak chatbot
- Embedding model:
  embed transcript chunks and user questions for retrieval
- Reranker:
  improve ordering of retrieved context when vector retrieval is enabled
- PII model:
  detect explicit PII entities before sending transcript content to the main analysis/chat model

Where they are used:

- [backend/medspeak/nvidia_nim.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/nvidia_nim.py)
- [backend/medspeak/agent_worker.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/agent_worker.py)
- [backend/medspeak/chat_service.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/chat_service.py)
- [backend/medspeak/pii_redact.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/pii_redact.py)
- [backend/medspeak/vector_store.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/vector_store.py)

### 3. Entelligence

`Entelligence` is not integrated as a runtime dependency in this codebase.

That means:

- there is no Entelligence API call in the backend
- there is no Entelligence SDK in the frontend
- the current MedSpeak app does not require Entelligence credentials to run

If you used Entelligence during ideation, research, product framing, or hackathon validation, it should be described as part of your broader workflow, not as a live runtime service in this repository.

### 4. Emergent

`Emergent` is also not integrated as a runtime dependency in this codebase.

That means:

- there is no Emergent API call in the backend
- there is no Emergent SDK in the frontend
- the current MedSpeak app does not require Emergent credentials to run

If you used Emergent as part of prototyping, planning, rapid iteration, or product direction, it is fair to describe it as a supporting development workflow tool, but not as a production/runtime component of this repository.

## Exact Runtime Architecture

### Frontend

The frontend is a Next.js app that:

- lets the user record audio locally in the browser
- lets the user upload an audio file manually
- lets the user load a demo transcript instantly
- lets the user choose autism mode and communication preferences
- sends the visit input to the backend
- polls the job status
- renders structured results
- downloads the generated PDF
- opens the MedSpeak chat drawer from the floating widget

Main frontend files:

- [frontend/src/components/app-shell.tsx](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/frontend/src/components/app-shell.tsx)
- [frontend/src/components/medspeak-drawer.tsx](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/frontend/src/components/medspeak-drawer.tsx)
- [frontend/src/components/results-tabs.tsx](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/frontend/src/components/results-tabs.tsx)
- [frontend/src/lib/api.ts](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/frontend/src/lib/api.ts)

### Backend

The backend is a FastAPI app with an internal background worker.

The backend:

- accepts requests
- stores job state in SQLite
- runs the processing pipeline asynchronously
- caches results
- returns job progress
- serves the generated PDF
- serves grounded chat endpoints

Main backend files:

- [backend/main.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/main.py)
- [backend/medspeak/agent_worker.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/agent_worker.py)
- [backend/medspeak/jobs.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/jobs.py)
- [backend/medspeak/pdf_export.py](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/medspeak/pdf_export.py)

## How MedSpeak Works

This is the exact processing flow used by the app.

### 1. Input capture

The user chooses one of these inputs:

- local browser recording
- uploaded audio file
- bundled demo transcript

### 2. Enqueue a job

The frontend sends the input to the backend:

- audio:
  `POST /api/analyze_from_audio`
- demo transcript:
  `POST /api/analyze_from_transcript`

The backend immediately returns a `job_id`.

### 3. Normalize audio

If the input is audio, the backend:

- writes the uploaded bytes temporarily
- runs `ffmpeg`
- converts the file to `16kHz` mono WAV
- checks length limits
- computes an audio hash for caching

### 4. Transcribe with smallest.ai

The backend sends the normalized WAV bytes to smallest.ai Pulse.

It requests:

- diarization
- word timestamps
- language mode

The backend then converts the provider response into a transcript.

### 5. Redact PII

The backend runs:

- NVIDIA `nvidia/gliner-pii`
- regex-based cleanup

It preserves person names for display in the current implementation, but redacts contact-style and identifier-style sensitive data.

### 6. Analyze with NVIDIA NIM

The backend sends the redacted transcript plus user preferences into the analysis model:

- `nvidia/llama-3.3-nemotron-super-49b-v1.5`

The model is instructed to return strict JSON only.

The structured output includes:

- standard summary
- autism-friendly summary
- intent summary
- intent timeline
- next steps checklist
- medications
- tests and referrals
- red flags
- questions to ask
- accommodation card
- social scripts
- uncertainties
- safety note

### 7. Verify and ground

The backend runs local verification checks so unsupported claims can be removed or normalized.

### 8. Index prior context

If Qdrant is enabled, the backend:

- chunks the transcript
- creates embeddings with NVIDIA embeddings
- stores them in Qdrant

This allows later retrieval of prior visit context.

### 9. Generate PDF

The backend generates a styled PDF with ReportLab that includes:

- visit summaries
- intent summary and timeline
- next steps
- medications
- tests and referrals
- questions to ask
- accommodation card
- scripts
- safety note
- returned transcript

### 10. Grounded chat

The MedSpeak chat is not a generic chatbot.

For every message it uses:

- current visit transcript
- current structured result
- prior visits if available
- visible website/app context

If evidence is missing, it falls back rather than inventing facts.

## Background Worker Stages

Each job moves through these stages:

1. `QUEUED`
2. `NORMALIZE_AUDIO`
3. `TRANSCRIBE`
4. `REDACT`
5. `ANALYZE`
6. `VERIFY`
7. `INDEX`
8. `RENDER_PDF`
9. `READY` or `FAILED`

## API Surface

### Analysis and jobs

- `GET /api/health`
- `POST /api/analyze_from_audio`
- `POST /api/analyze_from_transcript`
- `GET /api/job/{job_id}`
- `GET /api/download/{job_id}.pdf`

### Chat

- `POST /api/chat/start`
- `POST /api/chat/message`
- `GET /api/chat/history/{chat_session_id}`

## Storage

Local storage used by this repository:

- SQLite:
  jobs, transcripts, chat sessions, chat history, results
- local filesystem:
  uploaded audio, generated PDFs

Optional storage:

- Qdrant:
  prior-visit vector retrieval

## Environment Variables

Backend variables:

- `SMALLEST_API_KEY`
- `NIM_API_KEY`
- `NIM_LLM_MODEL`
- `NIM_CHAT_MODEL`
- `NIM_EMBED_MODEL`
- `NIM_RERANK_MODEL`
- `NIM_PII_MODEL`
- `USE_QDRANT`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `MAX_AUDIO_SECONDS`
- `REDACT_PII`

Frontend variables:

- `NEXT_PUBLIC_API_BASE_URL`

See:

- [backend/.env.example](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/backend/.env.example)
- [frontend/.env.example](/Users/chetasparekh/Library/CloudStorage/OneDrive-SanFranciscoStateUniversity/Hackathons/VoiceAI%20Hack%2014%20Mar/frontend/.env.example)

## Quick Start

### Backend

```bash
cd backend
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Install `ffmpeg` first:

```bash
brew install ffmpeg
```

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open:

- frontend:
  `http://localhost:3000`
- backend:
  `http://localhost:8000`

## How to Explain This Project

If you want to describe MedSpeak clearly, this is the accurate short version:

> MedSpeak is a voice medical-visit summarizer and grounded care companion. It records or uploads a visit, transcribes it with smallest.ai Pulse, analyzes it with NVIDIA NIM models, stores results locally, produces a polished PDF, and supports grounded follow-up chat from the visit record.

If you want to describe the tools precisely:

- smallest.ai:
  runtime speech-to-text provider
- NVIDIA NIM:
  runtime analysis, chat, embeddings, reranking, and PII detection provider
- Entelligence:
  not integrated in this repository runtime
- Emergent:
  not integrated in this repository runtime

## Tests

### Backend

```bash
cd backend
pytest -q
```

### Frontend production build

```bash
cd frontend
npm run build
```

### Demo smoke test

```bash
cd backend
python smoke_test.py
```

## Docker

Run the default stack:

```bash
docker compose up --build
```

Run with local Qdrant too:

```bash
docker compose --profile vector up --build
```

## Important Notes

- Secrets are not committed.
- Keep all API keys in local `.env` files only.
- MedSpeak is for note-taking and clarity.
- MedSpeak does not diagnose.
- MedSpeak does not provide new medical advice.
- Unsupported answers should be grounded down instead of invented.
