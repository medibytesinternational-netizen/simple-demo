# Plan: rolling the medibytes voice pipeline out beyond OPD (F1)

Status: draft, 2026-11-13. Branch base: `feat/opd-local-medibytes`.

## 1. Where we are

F1 (OPD consultation) voice notes now run in-process through `medibytes/`:

- `backend/app/services/pipeline.py` queues audio on `medibytes.api.jobs.JobService`
  with a note template chosen by `TEMPLATE_FOR = {"F1": "opd"}`, then `draft_content`
  maps the template's sections onto the feature's draft schema (each item keeps its
  proof sentence and `verified` / `needs_review` status).
- `medibytes/templates/` holds `NoteTemplate` / `SectionSpec`. Every feature section
  `behaves_like` one of the six measured discharge sections, so the verbatim gate,
  canonicalize, pre-fill and coverage rules are reused without change.
- `discharge` remains the default template and its prompts are pinned byte-for-byte
  (`tests/unit/test_discharge_template_pin.py`, `tests/fixtures/discharge_prompts_s1.json`).

Verification on 2026-11-13:

| Suite | Result |
|---|---|
| `backend/` pytest | 659 passed |
| `tests/` (medibytes unit + API + HIMS) | 497 passed |
| `tests/test_parity_phone40.py` | **42 errors**: `ReplayMiss`, no recorded reply for the discharge prompt |
| `frontend` `tsc --noEmit` | clean |

The Phone40 parity errors are not caused by the OPD work. The same failure happens when
the pre-refactor `medibytes/` (commit `8a7b2d7`) runs against the imported evaluation set.
The frozen baseline in `evaluation/phone40/baseline` was recorded with an older discharge
prompt. Fixing this is task 0 below, and it must be done before any template work, because
parity is the regression guard for the shared hardening code.

## 2. Hard-coded F1 assumptions to remove

| Location | Today | Needed |
|---|---|---|
| `backend/app/routes/notes.py` `/notes/transcribe` | `credits.charge(... feature="F1")`, no feature param | accept `feature` form field, validate against `TEMPLATE_FOR` |
| `notes.py` pipeline-status route | filters `TimelineEvent.subtype == "F1"`, `Draft.feature == "F1"` | use the feature stored in the audio index |
| `pipeline.py` `SECTION_LABELS` | OPD labels only | read labels from the template (`SectionSpec.label`) |
| `pipeline.py` `draft_content` | maps onto `ConsultNote` | one mapper per feature, registered next to the template |
| `frontend/src/pages/Notes.tsx` | the only `VoiceInput` user | `VoiceInput` takes a `feature` prop and posts it |

## 3. Candidate features

The app's draft schemas list which features produce clinical notes. Order them by how well
they fit dictation and how close they are to a measured section:

| Order | Feature | Draft schema | Fit | Notes |
|---|---|---|---|---|
| 1 | F4 Progress note | `ProgressNote` | high | SOAP-shaped; maps cleanly onto present_illness / examination / plan |
| 2 | F3 Ward round | `RoundDraft` | high | short, many per day; also feeds ward-round tasks |
| 3 | F2 Admission assessment | `AdmissionNote` | high | closest to OPD; reuse most OPD sections |
| 4 | F9 Discharge summary | `DischargeSummary` | high | the native `discharge` template; mapping only |
| 5 | F11 Referral | `ReferralDraft` | medium | short free text; one "reason" plus "findings" |
| 6 | F10 Investigation request | `InvestigationRequestDraft` | medium | structured list; needs an investigations extractor check |
| — | F7 ICU flow sheet | `ICUFlowSheet` | low | numeric readings; the form is faster. Revisit after vitals extraction is measured |
| — | F5, F6, F12, F13 | explanations | none | not dictated |

## 4. Work plan

### Task 0: Restore the parity guard (blocker)
1. Find the prompt drift: diff the prompt `ReplayLLMClient` asks for against the nearest
   recorded key in `evaluation/phone40/baseline`.
2. Decide which side is right. If the current prompt is intended, re-record the baseline
   with `evaluation/phone40/run_live_discharge.py` (needs an OpenAI key, costs one gpt-4.1
   pass over 40 clips) and re-score. The 212/229 target may move; record the new number.
3. If the drift was accidental, restore the old prompt text. The prompt pin snapshot must
   then be regenerated from the same source.
4. Done when `pytest tests/test_parity_phone40.py` is green.

### Task 1: Generalise the plumbing (no new feature yet)
1. Add `label` to `SectionSpec`, and a `mapper` per template (note sections to draft fields).
2. Make `/notes/transcribe` take `feature`; refuse unknown features with 400 before charging.
3. Store `feature` with the job (already in the audio index) and use it everywhere `"F1"`
   is hard-coded in the status route.
4. `VoiceInput` gets a `feature` prop. F1 keeps working without a visible change.
5. Tests: the existing F1 tests must pass unchanged. Add a test that an unknown feature is
   refused and charges no credit.

### Task 2: One feature per PR, in the order of section 3
For each feature:
1. `medibytes/templates/<name>.py`: sections, rules, one real-dictation example each,
   `behaves_like` for each. Examples must trim, not paraphrase (paraphrase fails canonicalize).
2. Register in `TEMPLATE_FOR` and add the draft mapper.
3. Mount `VoiceInput` on the feature's page (Progress, Tasks/ward round, PatientOverview
   admission, Discharge, referral and investigation forms).
4. Tests (section 5).
5. Small evaluation set (section 5) and a recorded score in the PR description.

### Task 3: Operations
- Job service: one worker thread today. Measure queue time once 3+ features record; add a
  worker count setting if p95 wait is above 30 s.
- Credits: charge per feature (`voice_note` with the real feature id) so the Revenue page
  shows which features use voice.
- Audit: the timeline event title is per feature, not "Consultation (MediBytes pipeline)".
- Failure states: surface `job_error` in the UI per feature, with a retry that does not
  charge again.

## 5. Testing strategy

| Layer | What | Where |
|---|---|---|
| Template unit | keys unique, every `behaves_like` valid, examples verbatim-trimmable, prompt snapshot pinned | `tests/unit/test_note_templates.py` (extend per template) |
| Discharge pin | discharge prompts unchanged byte-for-byte after every template PR | `tests/unit/test_discharge_template_pin.py` |
| Hardening | coverage, verbatim gate, canonicalize behave the same through a feature section as through its `behaves_like` section | new `tests/unit/test_template_hardening.py` |
| Mapper | note to draft: every section lands in the right field, proof sentence and status kept | `backend/tests/test_<feature>_voice.py` |
| API | upload, refuse without consent, refuse unknown feature, poll, draft created once per `audio_id`, credits charged once | `backend/tests/test_voice_upload.py` (parametrise by feature) |
| Replay | fake LLM via `medibytes.llm.replay.ReplayLLMClient` and fixed transcripts, so the CI never calls OpenAI | `tests/fakes.py` |
| Regression | Phone40 parity green (task 0) | `tests/test_parity_phone40.py` |
| Evaluation | 10 to 15 scripted dictations per feature, gold facts in `evaluation/<feature>/gold.json`, scored with the existing `scoring.py`; report recall of gold facts and the count of unsupported items (target: 0) | `evaluation/` |
| Frontend | typecheck; one Playwright run per feature: record (upload fixture audio), poll, review the draft, accept | `frontend` |
| Manual | a clinician reads 5 drafts per feature before the feature is enabled in the demo | checklist in the PR |

CI gate for every PR: backend pytest, `tests/` pytest including parity, `tsc --noEmit`.

## 6. Risks

- **Shared hardening changes leak into discharge.** Mitigated by the prompt pin and parity.
  Any change to `medibytes/llm/discharge.py` needs both green.
- **Section confusion** (e.g. assessment versus past history both behave like
  `previous_diagnosis`). Measure misplacement in the evaluation sets, not only recall.
- **Latency** with one worker thread once several features record at the same time.
- **Cost**: each note is one gpt-4.1 run plus repair passes. Track per feature in credits.

## 7. Definition of done for a feature

Template, mapper, UI mount, unit + API tests, an evaluation set with a recorded score and
zero unsupported items, parity and discharge pin green, clinician review checklist signed.
