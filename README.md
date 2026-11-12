# MediBytes

MediBytes processes a doctor's recorded dictation into a verified six-section discharge-note draft. The active backend and processing pipeline are Product's MediBytes implementation; the former Simple Demo HIMS backend has been removed.

The measured pipeline is preserved: audio preprocessing → MedASR → faster-whisper small-int8 second pass → drug extraction and fuzzy matching → gpt-4.1 term validation and context repair → verification → six-section note generation. Model settings and thresholds remain in `medibytes/config.py`.

## Requirements

- Python 3.11+
- Node.js 20+
- An OpenAI API key for gpt-4.1
- A Hugging Face token for `google/medasr` after accepting its model license
- ffmpeg is bundled for audio decoding by `imageio-ffmpeg`

## Install and run

From this project directory:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` and `HF_TOKEN` in `.env`. The first run downloads MedASR and faster-whisper model weights.

Start the API:

```bash
python -m medibytes.api
```

The API and built frontend use `http://127.0.0.1:8000`. For frontend development, use a second terminal:

```bash
cd frontend
cp .env.example .env   # optional; leave VITE_API_BASE_URL empty for the Vite proxy
npm ci
npm run dev
```

Vite serves `http://localhost:5173` and proxies `/api` to `http://127.0.0.1:8000`. To use another API origin, set `VITE_API_BASE_URL` in `frontend/.env` and allow the frontend origin in `MEDIBYTES_CORS_ORIGINS`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Pipeline, gpt-4.1 readiness and job counts |
| POST | `/api/jobs` | Upload a supported audio file; returns a queued job |
| GET | `/api/jobs` | Recent browser jobs |
| GET | `/api/jobs/{id}` | Job status, seven stages and completed result |
| GET | `/api/jobs/{id}/files/{name}` | Download an input or generated artifact |

Supported uploads: `.wav`, `.mp3`, `.m4a`, `.mp4`, `.aac`, `.flac`, `.ogg` and `.webm`; the API upload limit defaults to 64 MB. A missing `OPENAI_API_KEY` returns HTTP 503 for uploads.

The optional, separate HIMS integration is key-protected:

- `POST /api/v1/transcriptions`
- `GET /api/v1/transcriptions/{audio_id}`
- `POST /api/v1/transcriptions/{audio_id}/redeliver`

It queues audio and can deliver the resulting six-field note to a configured HIMS callback. See [`docs/HIMS_INTEGRATION.md`](docs/HIMS_INTEGRATION.md) for its contract and limitations.

## Frontend capabilities

The main screen supports audio upload, live job polling, the seven pipeline stages, recent jobs, audio playback and download, transcript review, extracted drug/vital/allergy/symptom rows, verification output, the six-section discharge note, and downloadable JSON/report artifacts. It keeps the Simple Demo's visual shell and shared design system while using Product's pipeline components.

The previous Simple Demo included broader HIMS operations. Product does not implement most of those operations. The **HIMS modules** screen lists what is not available; it does not issue writes or substitute fake data. In particular, the generated discharge note is an independent draft and does not sign a stay or update a patient chart. The optional callback is a transcript-to-note delivery integration, not a replacement HIMS.

See [`MIGRATION.md`](MIGRATION.md) for source-to-target mappings and removed functionality.

## Tests and checks

```bash
python -m pytest
python -m ruff check medibytes evaluation tests tools
cd frontend
npm run typecheck
npm test
npm run build
```

The Python tests use fake models/pipelines and do not download model weights. `evaluation/phone40/` retains Product's recordings, baselines, gold outputs, replay and scoring tools. Re-measure the real pipeline with:

```bash
python -m medibytes evaluation/phone40/audio --out runs/c1_check
python -m evaluation.phone40.score runs/c1_check
```

## Deployment

The root `Dockerfile` builds the frontend and runs the Python 3.11 API. Railway uses it and checks `/api/health`. Configure `OPENAI_API_KEY`, `HF_TOKEN`, `HF_HOME=/data/hf`, `MEDIBYTES_RUNS=/data/runs`, `MEDIBYTES_HOST=0.0.0.0`, `MEDIBYTES_PORT=8000` and `PORT=8000`; mount persistent storage at `/data`. The real pipeline needs about 1.6 GB peak memory and the first deployment downloads model weights.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | Yes for processing | gpt-4.1 review, context repair and note generation |
| `HF_TOKEN` | Yes for first model download | Authorized access to `google/medasr` |
| `HF_HOME` | No | Hugging Face cache directory |
| `MEDIBYTES_RUNS` | No | Job state and generated artifacts; defaults to `runs` |
| `MEDIBYTES_HOST` | No | API bind host; defaults to `127.0.0.1` |
| `MEDIBYTES_PORT` | No | API bind port; defaults to `8000` |
| `MEDIBYTES_MAX_UPLOAD_BYTES` | No | Upload cap; defaults to 64 MiB |
| `MEDIBYTES_CORS_ORIGINS` | No | Comma-separated origins allowed for a separately hosted browser frontend |
| `MEDIBYTES_LLM_TRACE` | No | Optional prompt/reply trace file; may contain clinical text |
| `MEDIBYTES_API_KEYS` | Only for HIMS API | Comma-separated bearer keys for `/api/v1/transcriptions` |
| `MEDIBYTES_HIMS_URL` | Only for HIMS delivery | HIMS receive endpoint |
| `MEDIBYTES_HIMS_TOKEN` | Only for HIMS delivery | Bearer token sent to the configured HIMS endpoint |
| `VITE_API_BASE_URL` | No | Optional absolute frontend API origin; blank uses same-origin `/api` |
