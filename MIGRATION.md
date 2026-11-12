# Backend migration record

## Active runtime

There is one active backend: Product's `medibytes` package. The Simple Demo `backend/` directory and its SQLite/FastAPI HIMS implementation were removed after the Product package, dependencies, runtime configuration, tests, evaluation data and integrated frontend had been copied into this project.

## Product source mapping

| Product source | Migrated destination |
|---|---|
| `Product-main/medibytes/` | `simple-demo-main/medibytes/` |
| `Product-main/requirements.txt` | `simple-demo-main/requirements.txt` |
| `Product-main/requirements-dev.txt` | `simple-demo-main/requirements-dev.txt` |
| `Product-main/pyproject.toml` | `simple-demo-main/pyproject.toml` (lint exclusion updated for `frontend/`) |
| `Product-main/.env.example` | `simple-demo-main/.env.example` (deployment and optional HIMS variables documented) |
| `Product-main/.gitignore` | `simple-demo-main/.gitignore` (combined with Simple Demo frontend/output ignores) |
| `Product-main/.python-version` | `simple-demo-main/.python-version` |
| `Product-main/conftest.py`, `tests/` | `simple-demo-main/conftest.py`, `simple-demo-main/tests/` |
| `Product-main/evaluation/` | `simple-demo-main/evaluation/` (audio, baselines, gold data, scripts and scoring retained) |
| `Product-main/tools/` | `simple-demo-main/tools/` |
| `Product-main/ARCHITECTURE.md` | `simple-demo-main/ARCHITECTURE.md` |
| `Product-main/docs/HIMS_INTEGRATION.md` | `simple-demo-main/docs/HIMS_INTEGRATION.md` |
| `Product-main/web/src/` | `simple-demo-main/frontend/src/medibytes/` (components, hooks, API types/client, fixtures and UI tests; `main.tsx` and Vite declarations remain at the Simple frontend entry point) |
| `Product-main/web/public/favicon.svg` | `simple-demo-main/frontend/public/favicon.svg` |
| `Product-main/web/package.json`, `package-lock.json`, `vite.config.ts`, `index.html` | `simple-demo-main/frontend/` equivalents (React scripts and dependencies merged; lock regenerated; Simple shell entry retained) |
| `Product-main/README.md` | `simple-demo-main/README.md` (rewritten with migration, install, runtime and API instructions) |
| `Product-main/railpack.json` | `simple-demo-main/railpack.json` (frontend build path and API start command aligned) |
| Product's `web/dist` runtime setting | `frontend/dist`; Vite and Docker/Railway now build `frontend/` |

The Product UI composition was expanded to render stage progress, recent jobs, audio, extracted chart rows, verification results and the discharge note. The API client also reads optional `VITE_API_BASE_URL`. Pipeline stages, thresholds, prompts and model configuration were not changed.

The copied `.env.example` leaves `OPENAI_API_KEY` and `HF_TOKEN` blank, so a fresh copy cannot accidentally report that model credentials are configured.

`evaluation/phone40/replay.py` now falls back from the cleaned-WAV hash to the frozen clip transcript identity when the host's bundled ffmpeg produces different WAV bytes from the Windows baseline. It reads the existing golden/cache files and does not rewrite evaluation data or affect production processing.

## Simple Demo paths changed or removed

- `simple-demo-main/backend/` — deleted after migration; its SQLite models, seed data, F1–F16 route handlers, old requirements and tests are no longer active.
- `simple-demo-main/frontend/src/pages/`, `features/`, `demo/`, legacy components and their generic HIMS API client/types — removed from the production frontend because their operations do not exist in Product's API.
- `frontend/src/styles/` — retained as the Simple Demo shared visual system; obsolete HIMS legacy overrides are no longer imported.
- `frontend/public/demo/` — removed unused synthetic OCR and claims previews that were only referenced by removed HIMS screens.
- `frontend/src/App.tsx`, `main.tsx`, `index.html`, `package.json`, `vite.config.ts` — replaced/updated for the integrated Product pipeline experience and API proxy.
- `Dockerfile`, `railway.json`, `.dockerignore`, `.gitignore` — updated for Python 3.11, the migrated frontend build and `python -m medibytes.api`.
- `netlify.toml` and `frontend/public/api-not-configured.json` — removed because they implemented the frontend-only preview and fake HIMS API configuration.
- `README.md` — replaced with the migrated install/run/API/deployment guide. Simple Demo PRD/review materials are archived under `docs/legacy-simple-demo/`; only Product's HIMS callback contract remains active documentation.

The supplied ZIP archives were used as read-only migration sources and are not included in this repository.

## Unsupported Simple Demo operations

The Product API does not replace these former Simple Demo operations. The UI routes them to a read-only capability page, and there are no fabricated API calls for them:

- patient registration/directory, patient-scoped chart/timeline, consent and patient state;
- F1–F4 HIMS note workflows, approvals, signing and encounter locking;
- clinical alerts, medication reconciliation, allergy verification and lab review;
- OCR document intake/confirmation/commit, investigation requests and referral lifecycles;
- HIMS discharge readiness/signing, claims/TPA, billing and revenue leakage;
- task assignment/escalation, hospital dashboards, audit and role-based access.

Product does include the separate key-protected transcription callback API documented in `docs/HIMS_INTEGRATION.md`. It sends the pipeline's note to one configured HIMS receive endpoint; it does not implement the operations listed above.

## Validation status

- Frontend typecheck, tests and production build passed. Frontend tests: 40 passed.
- The frontend uses React Router 7.18.5, Vite 5.4.21 and Vitest 2.1.9. `npm audit --omit=dev` reports no production dependency advisories; the full audit still reports 6 advisories in the development toolchain, whose offered fixes require further major version upgrades.
- Python Ruff passed. Python tests excluding `tests/test_parity_phone40.py`: 483 passed.
- The full Python run reaches 483 passed and 42 parity errors. The frozen `trace_discharge.jsonl` prompts predate the current Product discharge prompt, so exact replay raises `ReplayMiss` at note generation. No prompt or pipeline code was changed to hide that mismatch.
- A live server returned HTTP 200 from `/api/health` and served the built frontend at `/`. API job/upload/download tests pass with Product's fake pipeline.
- A real model-backed recording run was not available in this environment: `OPENAI_API_KEY` and `HF_TOKEN` are not configured. The full model path requires those credentials and a first-run model download.
- Docker image build was not run because the local Docker CLI has no reachable daemon. The Dockerfile installs `libgomp1`, required by the Linux Whisper runtime.
