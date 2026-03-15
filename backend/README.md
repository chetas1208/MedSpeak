# MedSpeak Backend

FastAPI backend for queued medical-visit analysis and grounded chat.

## What It Does

- Accepts uploaded audio at `POST /api/analyze_from_audio`
- Accepts demo transcripts at `POST /api/analyze_from_transcript`
- Normalizes audio to `16kHz` mono WAV with `ffmpeg`
- Calls smallest.ai Pulse STT with diarization
- Redacts PII with NVIDIA NIM `nvidia/gliner-pii` plus regex fallback
- Calls NVIDIA NIM `nvidia/llama-3.3-nemotron-super-49b-v1.5` for strict JSON extraction
- Stores jobs, transcripts, PDFs, chat sessions, and chat history in SQLite
- Optionally indexes prior visits in Qdrant
- Serves grounded MedSpeak chat endpoints

## Setup

```bash
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

## Environment Variables

- `SMALLEST_API_KEY`: required for smallest.ai Pulse STT
- `NIM_API_KEY`: required for NVIDIA NIM chat, embeddings, rerank, and PII extraction
- `NIM_LLM_MODEL`: defaults to `nvidia/llama-3.3-nemotron-super-49b-v1.5`
- `NIM_CHAT_MODEL`: defaults to `nvidia/llama-3.1-nemotron-nano-8b-v1`
- `NIM_EMBED_MODEL`: defaults to `nvidia/llama-nemotron-embed-1b-v2`
- `NIM_PII_MODEL`: defaults to `nvidia/gliner-pii`
- `NIM_RERANK_MODEL`: defaults to `nvidia/llama-nemotron-rerank-1b-v2`
- `USE_QDRANT`: enable prior-visit indexing and retrieval
- `QDRANT_URL`: local or cloud Qdrant URL
- `QDRANT_API_KEY`: optional, needed for Qdrant Cloud
- `MAX_AUDIO_SECONDS`: polite hard limit for uploads, default `300`
- `REDACT_PII`: default `true`
- `ENABLE_QA_AGENT_LLM`: optional repair pass, default `false`
- `PUBLIC_BASE_URL`: used for absolute PDF links

## API

- `GET /api/health`
- `POST /api/analyze_from_audio`
- `POST /api/analyze_from_transcript`
- `GET /api/job/{job_id}`
- `GET /api/download/{job_id}.pdf`
- `POST /api/chat/start`
- `POST /api/chat/message`
- `GET /api/chat/history/{chat_session_id}`

## Demo Smoke Test

Run the backend first, then:

```bash
python smoke_test.py
```

## Tests

```bash
pytest -q
```
