# MediBytes ARD — working demo

A runnable demo of the MediBytes ARD concept: a GPT-4o drafting layer over a seeded patient timeline, deterministic safety rules, evidence-linked drafts, human-only writes, and a complete audit trail.

Synthetic data only. Not for clinical use. No claim is submitted and nothing is sent to a payer, laboratory, specialist or external system.

## Stack

- **Backend** — Python 3.13, FastAPI, SQLAlchemy, SQLite
- **Frontend** — React 18, Vite, TypeScript, React Query
- **Model** — OpenAI `gpt-4o`, with a deterministic cached mode when no API key is present
- **Transcription** — OpenAI `whisper-1`, live mode only

The demo works fully without an API key. Cached drafts are generated from the same context objects as live drafts, and every screen, approval and audit path still works.

## Quick start

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env    # optional; add OPENAI_API_KEY for live GPT-4o and Whisper
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

### Validation on macOS/Linux

The browser suite runs against the synthetic cached preview and does not call the backend or OpenAI. Install the local toolchain once, then run the checks:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m compileall -q app
.venv/bin/python contract_check.py
.venv/bin/python -m pytest -q

cd ../frontend
npm install
npx playwright install chromium
npm run build
npm run test:e2e
```

### Production-style single server

```powershell
cd frontend
npm run build
cd ..\backend
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open **http://127.0.0.1:8000**. FastAPI serves the built React app.

### Deploy on Railway

The root `Dockerfile` builds the React app and serves it from FastAPI as one service; `railway.json` sets the health check (`/api/health`). Create a Railway service from this repo, mount a volume at `/data`, and set:

```env
DATABASE_URL=sqlite:////data/medibytes.db
UPLOADS_DIR=/data/uploads
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
LLM_MODE=auto
```

Keep it at one replica (SQLite). Leave `VITE_DEMO_MODE` unset; it is only for the Netlify preview.

## Live GPT-4o and Whisper

Copy `backend/.env.example` to `backend/.env` and set:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
LLM_MODE=auto
```

`LLM_MODE=auto` uses live GPT-4o when a key is present, otherwise cached drafts. Set `LLM_MODE=cached` to force deterministic drafts even with a key. Audio transcription is only available in live mode.

The header shows **Live GPT-4o** or **Cached demo**. Model, prompt version, latency and token counts are recorded in `llm_calls`; the UI shows them on every draft and in the audit log.

Do not commit `backend/.env` or the API key.

## The 16 modules

| Module | Workspace | What the demo implements |
|---|---|---|
| F1 Ambient OPD documentation | Notes → Consultation | Consent-gated transcript capture, live Whisper path, evidence-linked note draft |
| F2 AI-assisted admission | Notes → Admission | Admission draft from held records/interview, proposed orders, allergy verification gate |
| F3 Interdisciplinary handover | Notes → Round | Round note, proposed nursing-chart entries, proposed tasks accepted separately |
| F4 Daily progress notes | Notes → Progress | Drafts changes only; missing exam/plan stay empty and block signing until clinician-authored documentation is added |
| F5 Clinical Guardrail | Safety → Alerts | Rules R1–R6 over drugs, labs, contradicting notes and unresolved actions, with evidence |
| F6 Medication reconciliation | Safety → Medication reconciliation | Home vs current dose/route/frequency/indication, field-level differences |
| F7 ICU flow sheets | Notes → ICU chart | Device readings with units, timestamps and source; missing sections stay missing |
| F8 Medical OCR | Documents → Inbound | Original report beside extraction, confidence per field, human confirmation before commit |
| F9 Discharge summary | Discharge | Stay assembled from documented events, deterministic medication list, safety flags, lock |
| F10 Investigation/radiology forms | Documents → Requisition | Structured request with indication, diagnosis and allergies carried forward to verify |
| F11 Smart referrals | Notes → Referral | Drafted history and specific question, queue/acknowledge/specialist response tracking |
| F12 Insurance/TPA documentation | Revenue → Claim pack | Checklist, contradictions, TPA review state, underbilled and unsupported items, review-only HTML |
| F13 Revenue-leakage detection | Revenue → Leakage | Documented procedures vs charges; unbilled, underbilled and unsupported findings |
| F14 Hospital dashboard | Dashboard | Cross-patient queues, ward load, claim posture, discrepancies, audit and honesty panel |
| F15 Task/escalation engine | Tasks | Create, assign, acknowledge, start, complete, escalate and run an escalation sweep |
| F16 Unified patient timeline | Timeline | Append-only events, current-state projection, provenance and raw payload |

Two support views are deliberately not counted as PRD modules: **Notes → Labs (support)** for reviewing results, and **Documents → Follow-up (support)** for the outbound-document support workflow.

## Guardrails that are implemented

1. **The timeline is the source of truth.** Features read approved events through a whitelisted context slice. Drafts are not clinical state until approved.
2. **Rules decide, the model phrases.** R1–R6 are deterministic Python. The model cannot create or raise an alert.
3. **Every claim carries evidence.** Drafts cite `evt_` event ids and `seg_` transcript segment ids. The gateway checks unknown ids and re-prompts once in live mode; the UI shows a “No source” chip for unsourced claims.
4. **Human approval is the only write path.** `/api/drafts/{id}/approve` is the single commit endpoint for notes, requests, referrals, discharge and revenue reviews. Rejection requires a reason.
5. **Every write is audited.** Draft creation, edits, approvals, rejections, alert dismissal, lab review, OCR confirmation, task changes, referral transitions, transcription and claim preparation create `audit_entries`.
6. **F1 consent is explicit.** Audio cannot be transcribed until a human records `consultation_capture` consent. The model cannot record consent.
7. **F2 allergies are verified by a human.** Approval is blocked until the documented allergy is confirmed or corrected.
8. **F3 uses proposed tasks and proposed nursing entries.** Approving the note does not create tasks; accepting selected tasks does. Nursing entries become a separate nursing-chart event on note approval.
9. **F4 refuses to invent gaps.** Missing examination/plan sections stay visibly empty and signing stays blocked until a clinician documents them in the dedicated editor. That text is attributed to the clinician, not to the transcript.
10. **F5 dismissal needs a reason.** “Dismiss” is not a one-click mute.
11. **F8 keeps the source beside the value.** Low-confidence fields need human confirmation before commit. PDF text-layer extraction is supported; scanned PDFs without a text layer fall back honestly.
12. **F9 medication list is deterministic.** The model writes the narrative; code assembles discharge medications from active orders and flags active orders carrying open safety alerts. Narrative and follow-up claims without a source id are dropped before review, so an invented follow-up cannot be signed.
13. **F10 and F11 “send/export” do not transmit.** They are audited demo status transitions only.
14. **Revenue is review-only.** No submission, no charge, no payer connection. F12/F13 are review queues for a human.

### Seeded safety cases

- R1: metformin active with eGFR 22
- R2: flucloxacillin active with documented penicillin allergy
- R3: creatinine 2.9 mg/dL unreviewed and abnormal
- R4: warfarin + ibuprofen both active
- R5: allergy record contradicts a nursing note
- R6: unresolved plan action to hold metformin

### Seeded revenue cases

- Missing pre-authorization approval
- Wound debridement documented but not billed
- Physiotherapy billed with no supporting documentation
- IV antibiotics and physiotherapy seeded below expected amount
- Clinical contradictions on allergy documentation, metformin hold and IV antibiotic support
- Signing the discharge summary removes one required-document gap; pre-authorization remains

## Ten-minute demo path

1. **Timeline (F16)** — show the append-only record, current-state projection and source inspection.
2. **Notes → Consultation (F1)** — record consent, paste the seeded transcript or use a recorded WAV, generate, inspect evidence, approve.
3. **Safety (F5)** — show the six deterministic rules. Dismiss one with a reason; show the audit trail.
4. **Notes → Admission (F2)** — generate, verify the penicillin allergy as a human action, approve. Proposed orders stay drafts.
5. **Notes → Round (F3)** — generate, approve the note, inspect the nursing-chart entries, then accept selected tasks.
6. **Notes → Progress (F4)** — generate, show that missing exam/plan stay empty and signing is blocked, document both in the clinician-authored editor, then sign.
7. **Documents → Inbound (F8)** — open the seeded scan, confirm the low-confidence potassium, commit the results.
8. **Notes → ICU chart (F7)** — assemble the flow sheet from device readings; show units, timestamps and “not documented”.
9. **Notes → Referral (F11)** — draft a nephrology referral, approve, mark acknowledged, record the specialist response.
10. **Documents → Requisition (F10)** — draft the renal request, approve it and use the demo-only export state.
11. **Discharge (F9)** — generate and sign. The encounter locks; the signed summary removes one claim gap.
12. **Revenue (F12/F13)** — prepare the review pack, show contradictions/TPA state/underbilling, approve the explanation, then open Leakage and approve the findings.
13. **Tasks (F15)** — create, assign, acknowledge, start, complete and escalate work.
14. **Dashboard (F14)** — show hospital-scoped queues, ward load, claim posture and the honesty panel.

## Reset

The header **Demo** menu has two resets:

- **Fresh start** — demographics and allergy only; empty timeline.
- **Rehearsal data** — full seeded admission, ICU stay, labs, meds, alerts, tasks, documents, cohorts, bill and claim gaps.

Resetting replaces the SQLite database contents. Audit entries are reset too. The visible demo clock starts at 09:00 on 20 Oct 2026 and advances with real elapsed time, so new writes and overdue tasks stay consistent with the seed.

## Project layout

```text
backend/
  app/
    api.py              FastAPI routes
    modules.py          F1–F16 module registry (surface, gate, endpoints)
    models.py           SQLAlchemy tables
    seed.py             synthetic patient, cohort and reset modes
    clock.py            demo-time clock for writes and overdue logic
    schemas.py          draft schemas and feature registry
    prompts/            versioned prompt files per feature
    services/
      context.py        whitelisted context slices and evidence guard support
      llm.py            GPT-4o gateway, validation, call logging
      cached.py         deterministic cached drafts
      rules.py          R1–R6 safety rules
      drafts.py         draft lifecycle and approval side effects
      revenue.py        reconciliation, claim prep, leakage
      ocr.py            seeded scan, PDF text layer, OCR and confidence handling
      timeline.py       event store and current-state projection
  contract_check.py     offline F1–F16 contract check
frontend/
  src/
    components/         shell, evidence drawer, draft reviewer
    pages/              eight workspaces
```

## API snapshot

- `GET /api/meta` — patient, encounter, demo clock, LLM mode
- `GET /api/modules` — canonical F1–F16 registry with workspace, human gate and endpoints
- `GET /api/patients/pat_ravi/state` — current-state projection
- `GET /api/patients/pat_ravi/timeline` — append-only events
- `GET/POST /api/patients/{id}/consents` — F1 consent
- `POST /api/notes/transcribe` — live Whisper transcription, consent-gated
- `POST /api/notes/generate` — F1–F4 drafts
- `POST /api/drafts/{id}/approve|reject|accept-tasks|verify-allergy` — human writes
- `GET/POST /api/alerts...` — F5 queue, evaluate, dismiss with reason
- `GET/POST/PATCH /api/tasks...` — F15 work queue, assignment, acknowledgement, escalation sweep
- `GET/POST /api/documents...` — F8 upload, confirm-field, commit, image/PDF
- `POST /api/icu/flow-sheet/generate` — F7
- `POST /api/investigation-requests/generate` — F10
- `POST /api/referrals/generate` — F11
- `POST /api/discharge/generate` — F9
- `GET /api/revenue/claim-prep`, `POST .../prepare`, `POST .../explain`, `GET .../pack.html` — F12
- `GET /api/revenue/leakage`, `POST .../explain` — F13
- `GET /api/hospital/dashboard` — F14
- `GET /api/audit` — audit trail
- `POST /api/demo/reset?mode=start|rehearsal` — demo control

## Contract check

The module registry is explicit, not inferred from route names. It maps all 16 PRD modules to their workspace, human gate and mounted endpoints:

```powershell
cd backend
.\.venv\Scripts\python contract_check.py
```

The check is offline and prints `CONTRACT CHECK PASSED: 16 modules, N mounted paths`.

## Honesty matrix

### Working for real

- Navigation, all eight workspaces and every module view
- Timeline and current-state projection
- Rule engine (R1–R6)
- Draft generation, evidence guard, edit, reject, approve
- Consent capture and live Whisper transcription
- F2 allergy verification
- F3 proposed tasks, nursing-chart entries and acceptance
- F4 clinician-authored exam/plan editor with human attribution
- Task lifecycle, assignment, acknowledgement and escalation
- OCR confirmation and commit, including PDF text-layer extraction
- Referral and investigation request status transitions
- Claim checklist, contradiction checks, underbilling and leakage comparison
- Review-pack HTML, audit log and LLM call log
- Discharge readiness and signing
- Every model call in live mode

### Seeded or simulated

- Device feeds and vitals
- Patient identity, notes, labs and medication orders
- Cohort patients and their tasks/alerts
- Billing data and amounts
- Insurer/payer transmission (none — export only marks status)
- Value KPIs on the dashboard (illustrative, explicitly labelled)
- Demo transcript text (synthetic, editable in the UI)

## Notes and limitations

- This is a demo, not a medical device. No PHI should be entered.
- There is no authentication; the current user is fixed to Dr. Meera Shah.
- SQLite and synchronous model calls are adequate for a single-user demo, not production.
- Live OCR accepts images and text-layer PDFs. Scanned PDFs without a text layer fall back honestly rather than inventing values.
- The seeded scan is an SVG rendered by the backend, not a real image file.
- Dashboard value KPIs are illustrative and labelled as such.
- “Send”, “export”, “submit” and “charge” are never executed against an external system.
