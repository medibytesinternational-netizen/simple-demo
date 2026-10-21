# MediBytes ARD — Demo Architecture and UI Flow

Oct 20, 2026 · @medibytesinternational

A clickable prototype: a thin app around a general-purpose LLM, on seeded data for Ravi Menon plus a small cohort for the hospital dashboard. Built to be shown, not deployed.

| Layer | In this demo | In production |
| --- | --- | --- |
| Clinical reasoning | LLM call, versioned task prompt, JSON schema | Plus a licensed rules and drug database |
| Patient data | Seeded SQLite record for Ravi and a small cohort | FHIR integration with HMS and EMR |
| Speech | Consent-gated Whisper-1, with pasted transcript fallback | Clinical ASR with speaker separation |
| OCR | Vision model on an upload, plus PDF text-layer extraction | Medical OCR with layout and tables |
| Safety rules | Six hand-written rules for the demo cases | Licensed interaction and renal-dosing data |
| Tasks, audit, timeline | Real and working | Same, on a durable database |

Working for real: navigation, timeline, tasks, consent capture, Whisper transcription, review-and-approve, audit, PDF text extraction, claim contradiction and underbilling checks, every model call. Faked: device feeds, insurer submission, billing data, every dashboard number. Say so on stage, unprompted.

## Reference architecture

Deterministic code decides whether something is wrong. The model only writes the sentence that explains it.

&#91;embedded content: demo stack · client, orchestration, rules and gateway, seeded data\]

## The pattern every feature follows

Five stages, identical across all 16 modules. Only the context, the prompt and the output schema change — which is why the whole product is buildable by one small team.

**Trigger** a user action · **Context** pulled from the timeline, never raw tables · **Engine** rules first, model second · **Draft** JSON validated against a schema, every claim carrying its source event id · **Commit** a human approves, and only then does anything write.

## OPD Intelligence

One module. The doctor records the consultation; the note writes itself and waits for a signature. Highest demo impact for the least code — build it first.

&#91;embedded content: F1 · consultation note pipeline\]

Build notes: consent-gated Whisper-1 transcription with a pasted-transcript fallback, a two-pane review screen, and sentence-to-transcript source highlighting. About a week.

## IPD Intelligence

Six modules covering the stay from admission to discharge. They share one context source, so each one gets richer as the others run. F9 is the payoff module: it only looks impressive because F1 to F7 filled the timeline.

&#91;embedded content: F2, F3, F4, F7, F11, F9 · inpatient pipelines\]

Two details worth protecting in build: F3 shows proposed tasks as checkboxes so the user chooses which become real, and F4 renders examination and plan as empty required fields. The demo then documents them through a clinician-authored editor and attributes that text to the clinician, never to the transcript.

## Clinical Intelligence

Two modules, and the only place where the engine column is rules rather than model. The rule file fires the alert; the model phrases it. That boundary is the answer to "what if it hallucinates a warning".

&#91;embedded content: F5, F6 · safety pipelines\]

The demo rule file covers six cases: metformin below eGFR 30, the penicillin contradiction, an unreviewed result, warfarin plus ibuprofen, a contradicting allergy note, and an unresolved plan action. Dismissing an alert always demands a reason, which is the governance story in a single interaction.

## Document Intelligence

Two modules, one reading paper in and one pushing structured requests out. Low-confidence extractions stay yellow until a human confirms them; that visible hesitation is a selling point, not a defect.

&#91;embedded content: F8, F10 · document pipelines\]

Keep the original image or PDF beside the extraction on screen. Being able to point at the scan and then at the parsed value is most of the persuasion. Text-layer PDFs are extracted without inventing values; low-confidence fields wait for a human.

## Insurance Intelligence

Two modules, both deterministic comparisons with the model writing the explanation. Output is always a review queue, never an automatic charge or a live submission.

&#91;embedded content: F12, F13 · revenue pipelines\]

Seed the demo so pre-authorization is missing, wound debridement is documented but unbilled, IV antibiotics and physiotherapy are seeded below expected value, and three clinical contradictions require human resolution. All four gaps should be findable on screen in under ten seconds.

## Common infrastructure

Three modules that are not sold separately and must be built first. Every feature above reads the timeline and writes through the task store and audit log.

&#91;embedded content: F16, F15, F14 · infrastructure services\]

The timeline is the only place that decides what is current and what is superseded. Get that wrong and every feature above inherits the error.

## UI flow

One primary patient, a small hospital cohort for the dashboard, eight screens, one path. A left nav shows all eight so the product looks whole; the demo walks them in order.

&#91;embedded content: screen map · 8 screens in demo order\]

Each screen ends in an approval that writes to the timeline, and the timeline is where the next screen gets its context. The patient header never changes, so a client who clicks away stays oriented.

## Design system

Dense, quiet, legible — closer to a banking console than a consumer AI product. One neutral ramp for most of the interface, one accent for primary actions, status colours used only for status: red critical, amber unverified, green approved, blue AI-assisted. Interface sans plus a monospace for doses and lab values. Four type sizes: 20, 15, 13, 11. Eight-point grid, 56-pixel header, 240 left nav, 320 right rail, 36-pixel table rows. Almost no motion: streaming text while a draft generates, one transition on approve.

Design these states explicitly, because skipped states are what make a demo look dishonest: generating, draft ready, human-edited, approved and signed, rejected with reason, low confidence, model unavailable.

## Build path

Six weeks, in an order where you always have something to show. Phase 3 is tinted because it is the one that decides whether the product is a scribe or a safety system.

&#91;embedded content: build path · 4 phases, 4 gates\]

Inside those phases, build in this order. Each step wires into something already built, and each one ends with something you can show — never build two steps before demoing either.

| # | Build this | Wires into | You can now show |
| --- | --- | --- | --- |
| 1 | Patient store with the Ravi seed | nothing yet | The seeded record as raw data |
| 2 | Timeline service over the store | step 1 | Events in order, with source and author |
| 3 | App shell, left nav, patient header | step 2 | Clicking around a real-looking product |
| 4 | LLM gateway: prompt file, schema, retry, audit | nothing yet | A test task returning valid JSON |
| 5 | F1 ambient note | steps 2, 3, 4 | Speech becomes a draft note on screen |
| 6 | The review-and-approve component | step 5 | Approving writes the note to the timeline |
| 7 | Rule file and F5 alerts | steps 2, 6 | The metformin catch, with the lab attached |
| 8 | F6 reconciliation | steps 2, 7 | Home list against current plan, alerts link into it |
| 9 | Task store and F15 states | step 3 | Tasks moving created to completed, overdue flagged |
| 10 | F3 round handover | steps 4, 6, 9 | Dictation becoming three accepted tasks |
| 11 | F8 OCR | steps 2, 4, 6 | An upload becoming a sourced value on the timeline |
| 12 | F9 discharge summary | steps 5, 7, 10, 11 | A summary citing everything built so far |
| 13 | F2, F4, F7, F10, F11 | the same parts | The rest of the inpatient stay |
| 14 | F12 claim pack and F13 leakage | steps 2, 12 plus a seeded bill | One missing document, one unbilled procedure |
| 15 | F14 dashboard | all stores | Counters that move when you work the demo |

Step 6 is the one to get right, because every later feature reuses it. If each intern owns one row and they share steps 1 to 6, the rest can be built in parallel. Step 12 is the proof that the connections work: if the discharge summary can cite the note from step 5, the alert from step 7 and the lab from step 11, the platform is genuinely joined up rather than fifteen screens side by side.

## Demo script, ten minutes

1. **Open Ravi's timeline.** Show the seeded admission, the append-only events and the current-state projection.
2. **The consultation.** Record consent as a human action; play or paste the conversation; the note writes itself with sources. Edit a line, approve.
3. **The catch.** Open Safety. The metformin alert fires with the eGFR 22 lab attached, beside five other deterministic rules. Dismiss one — the system demands a reason. This is the moment that sells.
4. **The round and the progress note.** Accept three of the proposed tasks. On the progress note, show that exam and plan refuse to appear, then document them in the clinician-authored editor and sign. Assemble the ICU flow sheet from device readings.
5. **Old records and requests.** Upload a text-layer creatinine PDF, confirm the low-confidence field, commit. Draft the renal requisition and nephrology referral; both “send/export” actions are demo status only.
6. **Discharge.** Generate the summary, show the metformin safety flag and deterministic medication list, then sign and lock the encounter.
7. **The money.** Prepare the claim review pack: one missing pre-authorization, three contradictions, two underbilled items. Approve the explanation and the leakage findings. Nothing is submitted or charged.
8. **The hospital view.** Fifteen seconds on the dashboard, no more. Then say plainly what was real and what was seeded.
