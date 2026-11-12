# Hospital-Demo vs MediBytes PRD — gap report

- Date: 2026-10-21
- Repo tested: `medibytesinternational-netizen/Hospital-Demo`, `main` @ `aade9c4`, cloned to `~/Projects/Hospital-Demo-ARD`
- Spec: `docs/PRD.pdf` (5 pages). The repo's own `MediBytes PRD — Intern Onboarding Guide.md` is the same text plus an "Open questions" section, so there is no spec drift.
- Mode tested: cached (no API key). The only OpenAI key available was rejected earlier, so GPT-4o and Whisper were never run.
- Live path: I also ran one live-mode call against a local `llama3.2:3b` through `OPENAI_BASE_URL`. That checks the plumbing only. It says nothing about GPT-4o quality.
- UI: `npm run build` (tsc + vite) passes. I did not open the UI in a browser; every verdict below comes from the API and the code.

## 1. Answer

The code is **not 1-to-1 with the PRD**. All 16 modules exist as a screen and a set of routes, but behaviour only matches the PRD in some of them.

| What I could run | Count |
|---|---|
| Modules whose PRD line is fully met | **4 of 16**: F5, F12, F14, F16 |
| Met, but on seeded data only | 1: F7 |
| Partly met | 8: F2, F3, F4, F6, F9, F11, F13, F15 |
| Partly met and crashing in cached mode | 1: F10 |
| Core claim unverifiable without a live key | 2: F1, F8 |

Per PRD clause (38 clauses, section 3):

| Verdict | Count |
|---|---|
| Verified working | 13 |
| Implemented but seeded or simulated | 1 |
| Partial | 15 |
| Missing | 6 |
| Not verifiable here (needs the live model) | 3 |

I am not giving a single percentage. A percentage would hide the biggest issue, which is that "works" in cached mode means different things for different modules.

### The five things that matter most

1. **Cached drafts are canned text, not drafts from the input.** With a non-seed asthma transcript, cached F1 still wrote "cellulitis of the right lower leg… hold metformin", and cited segments that don't say that. On an empty record, F2, F4 and F11 still invent a history ("58-year-old man", "eGFR 22" with no labs). This breaks PRD rules 2 and 3. (D1)
2. **F10 returns HTTP 500 on the seeded patient.** README demo step 10 cannot be run without a key. (D2)
3. **F8 ignores the uploaded file in cached mode.** A PDF with creatinine 1.0 came back as 3.1. (D3)
4. **"Locked" encounters are not locked.** After discharge, a new note was approved and a new task created. An empty discharge summary on an empty chart was also approved. (D4)
5. **Modules share a record, but not roles, integrations or credits.** The "enter once, reuse five times" claim (PRD p.3) does hold. Nurse, pharmacist and billing views, HMS/EMR integration and credit metering do not exist.

### What is genuinely good

- Single write path: nothing reaches the timeline except `POST /drafts/{id}/approve` (PRD rule 1 holds).
- F1 consent and F2 allergy gates are real. F4 refuses to approve until a clinician documents the exam and plan.
- Rules R1–R4 and R6 are deterministic with evidence links, and the model only phrases them.
- F6 reconciliation compares dose, route, frequency and indication. F12 and F13 respond to inputs; signing the discharge removed one claim gap.
- Reuse is real: a newer eGFR injected into the timeline reached F5, F6, F9, F11 and F16 with no further work.
- Drafts never write state, and F9's medication list is built by code, not by the model.

## 2. How I tested

| Step | Result |
|---|---|
| `contract_check.py` | PASSED: 16 modules, 66 mounted paths. It checks only that registry fields are non-empty and routes exist, so it says nothing about behaviour. |
| `npm run build` | passes (89 modules) |
| Probes | 12 scripts in `docs/prd-probes/` run against `LLM_MODE=cached`; they assert behaviour, not status codes. Run order: start the server, then `python3 -I p1.py docs/prd-probes` and so on. |
| Fresh-start reset | used to test "never invent" on an empty timeline |
| Harness injection (`inject.py`) | writes a newer lab and a "stopped" order through the app's own `add_event`, standing in for an inbound feed (the app has no inbound API) |
| Static scan (`scan.py`) | for roles, FHIR/HMS, credits, schedulers, precision metrics |

Verdict key: **V** verified working · **S** implemented but seeded/simulated · **P** partial · **M** missing · **N** not verifiable here.

## 3. Clause-by-clause matrix

| # | PRD clause | Verdict | Evidence |
|---|---|---|---|
| 1 | F1 consent before capture and sign-off | V | Approve without consent → 400 (`drafts.py:292-308`); transcribe is consent-gated (`api.py:640-649`) |
| 2 | F1 listens to the consultation | N | Audio path is Whisper-1 live only (`api.py:650-651`); recorder UI exists (`Notes.tsx:140-156`) |
| 3 | F1 drafts the note from the conversation | N | Cached mode ignores the transcript (probe p1). Live plumbing ran, but the 3B model returned an all-null draft and it was saved as `status: ok` (p11, p12) |
| 4 | F2 allergies flagged and human-verified | V | Approve blocked until `verify-allergy` (`drafts.py:280-291`); proposed orders did not become active orders |
| 5 | F2 pre-fills from records already held | P | Problems and labs are pulled in; narrative, exam and proposed orders are hardcoded (`cached.py:164-218`); on an empty chart it still wrote a cellulitis admission |
| 6 | F3 round instruction → tasks, accepted separately | V | 4 tasks proposed from the transcript; the board stayed at 4 until `accept-tasks` |
| 7 | F3 → note and nursing chart | P | `nursing_chart` event is written on approve, but the note and nursing text are canned (`cached.py:258-286`) and invent "ibuprofen increase was not accepted" |
| 8 | F4 exam/plan never invented, clinician-authored | V | Approve with empty exam/plan → 400 |
| 9 | F4 "what changed since the last note" | P | No comparison with the previous note exists; objective is vitals only; subjective is canned (`cached.py:303-323`); labs are ignored |
| 10 | F5 checks drugs, labs, contradicting notes, unresolved actions, with evidence | V | R1–R6 present with evidence ids (`rules.py`) |
| 11 | F6 compares dose, route, frequency, indication | V | Field-level deterministic comparison (`revenue.py:28-167`); after metformin was stopped the discrepancy changed |
| 12 | F6 "clinician reviews each discrepancy" / pharmacist queue | M | No per-discrepancy decision state or endpoint; only a whole-draft approve |
| 13 | F7 device readings → chart with units, timestamps | S | 10 entries, all with device, timestamp and source id, but from seeded events; no ingest endpoint |
| 14 | F8 keeps the original, marks uncertain readings | V | Original served at `/documents/{id}/image`; confidence < 0.8 blocks commit until confirmed |
| 15 | F8 reads uploads into structured values | N | Cached mode ignores the file and returns the seeded values (`ocr.py:199-200`); text-layer PDF parsing exists only in the live branch |
| 16 | F8 "reports" generally | P | `doc_type` is fixed to `lab_report` (`api.py:1160`) |
| 17 | F9 assembled from documented events only | P | Sources are enforced, deterministic medication list, empty on an empty chart. But cached follow-up and red-flag text is invented and tagged with lab evidence (`cached.py:543-553`) |
| 18 | F9 doctor approval | P | Approval is required, but nothing is gated on readiness or open safety flags, and the lock is not enforced (D4) |
| 19 | F10 pre-fills indication, diagnosis, allergies | P | Crashes with HTTP 500 on seeded and empty records (D2); live output untestable |
| 20 | F10 allergies "to verify" | M | No verification gate on approve or export (`drafts.py:321-342`, `api.py:1263-1280`); the verify endpoint is F2-only (`api.py:553`) |
| 21 | F11 history and a specific question | P | Question and history are fixed nephrology/Ravi text; asking for Cardiology only relabels it (`api.py:1300`) |
| 22 | F11 tracks the consult | V | approve → sent → acknowledged → completed, each with a timeline event |
| 23 | F12 builds the claim pack, checks completeness | V | Status moved after signing the discharge: missing `signed_discharge` cleared, `pre_auth` remained |
| 24 | F12 flags contradictions before submission | V | 3 contradictions found; HTML review pack exists |
| 25 | F13 documented services vs charges | P | Only procedures vs a seeded bill, matched by substring (`revenue.py:251`), with seeded expected amounts |
| 26 | F14 pending tasks, drafts, claims, discrepancies | V | Counters moved after real actions (overdue +1, open alerts −1) |
| 27 | F15 created → assigned → acknowledged → completed | P | Endpoints exist, but `PATCH` allows any jump: created → completed, completed → proposed (`api.py:1105-1128`); anyone can acknowledge |
| 28 | F15 "escalates what stalls" | M | Escalation only happens when someone POSTs `/tasks/escalations/run`; there is no scheduler. A manual escalate needs no reason, although the registry says it does (`modules.py:452`) |
| 29 | F16 every event in order, with who, when, source | V | Superseded events stay visible with lineage |
| 30 | Rule 1 draft, do not decide | V | Drafts write nothing; one approve path |
| 31 | Rule 2 never invent | P | Cached mode violates it (D1). Live mode has evidence and number validators (`llm.py:62-75`), but a failed live call silently falls back to the canned text (`llm.py:239-242`) |
| 32 | Rule 3 show the evidence | P | Event ids resolve. Cached segment citations are false, and approval validates only `evt_` ids, not `seg_` ids (`drafts.py:240-249`) |
| 33 | Rule 4 said ≠ ordered ≠ done | P | Round → proposed tasks and proposed orders work. A task can be completed without acknowledgement. There is no way to order, stop or administer a drug, so "a prescription is not an administration" cannot be exercised; `meds_administered` is always empty |
| 34 | Rule 5 integrate by API | M | No FHIR, HL7, HMS or EMR code; data is seeded SQLite, and there is no inbound feed endpoint |
| 35 | Role-specific products | M | One fixed user, "Dr. Meera Shah", for every action; no auth, no role views. The assignee dropdown lists names only (`Tasks.tsx:18`) |
| 36 | Alert precision as a requirement | P | A new eGFR created a **second** open R1 (and a second R3) for the same problem; stopping metformin left R1 and R6 open; there is no precision measurement |
| 37 | Commercial model: AI credits per operation | M | Tokens are logged per call (`LLMCall`), but there is no credit table, cost schedule, pack or balance |
| 38 | Patient journey across many patients | P | Four cohort patients exist only as dashboard rows: one seeded task each (alerts for two), zero timeline events; every workflow is hard-wired to Ravi (`api.py:162-171`) |

Totals: V 13 · S 1 · P 15 · M 6 · N 3.

## 4. What does not match, and how to make it match

Ordered by priority. Sizes are rough: **S** is hours, **M** is a few days, **L** is over a week.

### Make the shipped (no-key) mode honest

**D1 — Cached drafts are canned (F1, F2, F3, F4, F9, F11) · M**
- Evidence: p1, p2.
  - Asthma transcript → cellulitis note.
  - Empty chart → "58-year-old man… eGFR 22".
  - F9 follow-up "Repeat creatinine within one week" is invented, with lab ids attached.
  - Also hardcoded: `cached.py:90-153`, `164-218`, `258-286`, `303-323`, `445-449`, `482-495`, `543-553`, and `revenue.py:75`, `84`.
- Fix:
  1. Replace the fixtures with extractive generators. Split the transcript by speaker, classify segments (complaint, history, exam, assessment, plan) with simple rules, and quote them with their real `seg_` ids.
  2. Leave a section empty and list it under `not_documented` when nothing supports it.
  3. Build F9 follow-up and red flags only from documented plan fields.
  4. Add a regression test: the asthma transcript must never contain "cellulitis", and an empty chart must produce only empty sections.
- Alternative if you want less work: in cached mode, serve the canned note only when the transcript is the seeded one, and otherwise return a visible "needs live model" error. That is honest, but it makes the no-key demo narrower.

**D2 — F10 crashes (HTTP 500) · S**
- Evidence: p2, p4; the server log shows `allergies_to_verify.0.substance: Input should be a valid string`.
- Cause: `cached.py:400-408` passes each allergy dict as the `substance` string, but `context.py:115-128` already turns allergies into dicts. F2 handles this correctly at `cached.py:209-216`.
- Fix: read `substance`, `reaction` and `event_id` from the dict, as F2 does. Also catch `DraftGenerationError` in every generate route; today only `/notes/generate` does (`api.py:704`), so every other schema failure is a 500. Add a test that generates all 11 drafts on the rehearsal and fresh-start records.

**D3 — F8 ignores the upload in cached mode · M**
- Evidence: p6 (PDF with creatinine 1.0 / eGFR 88 / K 4.1 → 3.1 / 21 / 5.3).
- Fix: when there is no key, run `_pdf_text` (already in `ocr.py:130`) and parse `name value unit (range)` rows into fields, with lower confidence for ambiguous lines. For images or PDFs with no text layer, return an empty extraction with `needs_manual_entry`, never the seeded values. Keep the seeded scan only for the seeded document. This also makes README demo step 7 true without a key.

**D14 — Reject empty or unsourced output · S**
- Evidence: p11, p12 (a live draft with every field null was stored as `status: ok`, no validation errors).
- Fix: in `llm.py:288-306`, treat a draft with no claims as `empty_output` and show "the model returned nothing" instead of a normal draft. Validate `seg_` ids at approve (`drafts.py:240-249`). Show a "model unavailable" state instead of silently substituting canned text on a failed live call (`llm.py:239-242`).

### Enforce what the PRD and README promise

**D4 — Discharge lock and readiness · S**
- Evidence: p3, p4. After discharge, a new F4 note was approved (200) and a new task was created (200). An F9 draft with no sections and no meds was approved on an empty chart.
- Fix: add one guard that returns 409 when `encounter.status != "active"`, called from `approve_draft`, `accept_tasks`, `task_create`, and the generate routes. Gate F9 approval on `/discharge/readiness` (already computed at `api.py:1476-1502`), and require every open critical alert to be acknowledged or dismissed with a reason, or recorded as an explicit override.

**D5 — F10 allergy verification · S**
- Copy the F2 gate (`drafts.py:280-291`) into the F10 approve path and let `verify-allergy` accept F10 (`api.py:553`).

**D6 — F15 automatic escalation and a real state machine · S–M**
- Evidence: p5. A task 6 hours overdue stayed at level 0 until `POST /tasks/escalations/run`.
- Fix:
  1. Move the sweep into a service function.
  2. Call it from a startup loop (an `asyncio` task every minute) and lazily on `GET /tasks` and `/hospital/dashboard`.
  3. Add a transition table for `PATCH` (created → assigned → acknowledged → in_progress → completed; reopen only with a reason).
  4. Require `reason` on manual escalation.
  5. Require the acknowledger to be the assignee.

**D7 — Alert lifecycle and precision (F5) · M**
- Evidence: p7.
  - A new eGFR created a second open R1 (`rules.py:102`, key includes the lab event id; R3 `:144`).
  - Stopping metformin left R1 and R6 open.
  - R5 fires only if a note payload has `allergies == []` or `assertion == "no_known_allergies"` (`rules.py:203`), which only the seed sets, so notes written in-app can never trigger it.
- Fix:
  1. Key alerts by (rule, drug or lab name, patient), and update the evidence ids in place when a newer result arrives.
  2. On each evaluation, auto-resolve alerts whose condition is no longer true, with an audit entry.
  3. For R5, add a text check at note approval like the one in `revenue.py:296`.
  4. Make the dismissal reason a category (`false_positive`, `known_and_accepted`, `acted_on`) and show per-rule precision on the dashboard. That also answers the PRD's open question on how a false-positive rate is measured in pilot.

### Missing features

**D8 — F6 per-discrepancy resolution and the pharmacist queue · M**
- Add a `reconciliation_decisions` table (discrepancy id, decision `continue|hold|stop|change`, by, at, note) and `POST /medications/reconciliation/{id}/resolve`. A decision creates a proposed order change that still needs clinician approval. Add a queue view filtered to open discrepancies.

**D9 — Orders and administrations (rule 4) · M**
- `timeline._medications` already understands `status: "stopped"` (`timeline.py:184`) and `medication_administration` is already a known event type (`context.py:103`), but no route writes either. Add draft → approve for order changes, and a `POST` to record an administration. Then F7 and F9 can report real `meds_administered`, and R1/R6 can resolve when an order is stopped.

**D10 — F4 delta since the last note · M**
- In `build_context`, for F4 include the previous progress note and every event after its `occurred_at`. Compose the objective section from new labs, vitals, orders and tasks, each with its source id. Keep subjective strictly from transcript segments.

**D11 — F13 breadth · M**
- Compare documented medications administered, investigations, consults and bed-days against bill lines, not just procedures. Match by code (`BillLineItem.code` ↔ procedure code) instead of substring (`revenue.py:251`), and use a tariff table instead of per-row `expected_amount`.

**D12 — F11 specialty and question · S**
- Derive the specialty and question from the triggering alert or lab (R1 → nephrology). If the user picks a specialty, generate the question for it instead of overwriting the label (`api.py:1300`).

**D15 — Roles (nurse, pharmacist, billing, management, doctor) · M**
- Add a `users` table and a session endpoint, and replace `settings.demo_user` (about 30 uses) with a `current_user()` dependency. Add `require_role()` on approve, verify, dismiss and commit (clinician) and on revenue (billing). Give each role a home view: nurse "my tasks", pharmacist reconciliation queue, billing claim pack, management dashboard. The four assignees already exist in `Tasks.tsx:18`.

**D16 — Rule 5, integrate by API · L**
- Add an adapter layer with FHIR R4 mappers (Patient, Encounter, Observation, MedicationRequest, AllergyIntolerance) and `POST /api/ingest/fhir` that writes timeline events with `source="fhir:<system>"`. Add outbound writes on approve. Cover the PRD's open question on drops mid-shift with a retry queue and a "last synced" banner. Test it against a mock FHIR server.

**D17 — AI credits · S–M**
- Add a `credit_ledger` table and the PRD's schedule (OCR 1, voice note 2, medicine reconciliation 2, report analysis 4, discharge summary 5). Write a row in `generate_draft`, `run_ocr` and transcribe, referencing the existing `LLMCall` id. Add a balance endpoint and header meter, with 5,000 / 15,000 / 50,000 packs. The PRD leaves the OCR unit open (page or document), so it needs a decision first.

**D18 — More than one patient · M**
- `_state(db)` always returns the current patient (`api.py:162-171`). Add `patient_id` to the generate and task routes and a patient selector, and give the four cohort patients real timelines (they have none today) so the dashboard rows have something behind them.

**D19 — F7 device ingestion · S–M**
- Add `POST /api/icu/readings` (device, value, unit, timestamp, dedupe) and route entries to the right chart by category.

**D20 — F8 report types · M**
- `doc_type` is fixed to `lab_report` (`api.py:1160`). Add discharge summaries, prescriptions and radiology reports, each with its own extraction schema.

**D21 — F16 authorship · S**
- Approved AI notes are stored as `author_type="model"` with `author_name` set to the approving doctor (`drafts.py:391-392`), so the timeline shows a clinician as author of model text. Store `drafted_by` (model, prompt version) and `approved_by` separately and show both.

### Suggested order

1. D2, D4, D5 (small, user-visible, remove crashes and false promises).
2. D1 and D3 (make the no-key demo honest).
3. D14, D6, D7, D9 (safety and workflow integrity).
4. D8, D10, D12, D15 (the role and workflow features).
5. D16, D17, D18, D11, D19, D20 (platform scale).

## 5. What I could not verify

- GPT-4o and Whisper behaviour: F1 drafting from audio, F8 reading real scans, live-mode quality of every draft. These need a working OpenAI key. The three N verdicts depend on this, and the live path may well do better than the cached results above.
- The UI beyond type-checking: nothing was inspected in a browser.
- Alert false-positive rates (no pilot data exists).
- The FHIR, billing and TPA integrations the PRD mentions (none are built, so there was nothing to run).
