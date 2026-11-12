# MediBytes PRD — Intern Onboarding Guide

Oct 20, 2026 · @medibytesinternational

MediBytes is an intelligence layer over a hospital's existing HMS and EMR. It captures clinical information once, checks it for contradictions, routes the resulting work to the right people, and makes sure documented care is billed. Everything below is intended behaviour, not shipped capability.

The problem is not missing software. Each department keeps its own record — doctors, nurses, pharmacy, lab, billing, insurance — so the same fact is asked for, typed and stored many times, and the copies drift apart.

## The five categories

Customers buy five intelligence products. The 16 modules sit underneath, on common infrastructure for patient records, task management and analytics.

| Category | What the hospital buys | Modules |
| --- | --- | --- |
| OPD Intelligence | Consultation notes drafted from the doctor–patient conversation | F1 |
| IPD Intelligence | Inpatient documentation end to end: admission, rounds, nursing, ICU, referrals, discharge | F2, F3, F4, F7, F9, F11 |
| Clinical Intelligence | Cross-checks across diagnoses, drugs, labs, orders and plans to surface errors and omissions | F5, F6 |
| Document Intelligence | Paper and uploads turned into structured, searchable data; forms filled from it | F8, F10 |
| Insurance Intelligence | Claim packs prepared, incomplete claims and missed revenue detected | F12, F13 |
| Common infrastructure | Unified patient record, task tracking, hospital analytics | F14, F15, F16 |

## The 16 modules

| # | Module | In one line |
| --- | --- | --- |
| F1 | Ambient OPD documentation | Listens to the consultation, with consent, and drafts the note for approval |
| F2 | AI-assisted admission | Pre-fills the admission file from records already held; flags allergies to verify |
| F3 | Interdisciplinary handover | Turns one verified round instruction into the note, the nursing chart and the task board |
| F4 | Daily progress notes | Drafts today's entry from what changed since the last note |
| F5 | Clinical Guardrail | Checks drugs, labs, contradicting notes and unresolved actions, with evidence attached |
| F6 | Medication reconciliation | Compares home list against current plan on dose, route, frequency and indication |
| F7 | ICU flow sheets | Pulls device readings and structured entries into the right chart, with units and timestamps |
| F8 | Medical OCR | Reads uploaded reports into structured values; keeps the original, marks uncertain readings |
| F9 | Discharge summary | Assembles the stay from documented events only, for doctor approval |
| F10 | Investigation and radiology forms | Pre-fills the request with indication, diagnosis and allergies to verify |
| F11 | Smart referrals | Sends the specialist the history and the specific question; tracks the consult |
| F12 | Insurance and TPA documentation | Builds the claim pack, checks completeness, flags contradictions before submission |
| F13 | Revenue-leakage detection | Compares documented services against charges and flags mismatches |
| F14 | Hospital dashboard | Pending tasks, draft discharges, claims and discrepancies for management |
| F15 | Task and escalation engine | Created, assigned, acknowledged, completed — then escalates what stalls |
| F16 | Unified patient timeline | Every event in order, with who recorded it, when and from which source |

## How it fits together

&#91;embedded content: platform layers · inputs, shared record, five categories, infrastructure\]

Ravi's kidney result, entered once, is used five times: the Guardrail checks metformin against it, the progress note summarises it, the referral carries it as context, the discharge summary reports it, the timeline dates it. That reuse is the reason to build one platform rather than 16 apps.

## The patient journey

&#91;embedded content: patient journey · 5 stages, 16 modules\]

Each role sees a different product. The doctor reviews drafts instead of typing them. The nurse gets round instructions as owned tasks. The pharmacist works a queue of medication differences. Billing opens a claim pack that is already assembled. Management watches where work is stuck.

## Five rules every module obeys

1. **Draft, do not decide.** Orders, medication changes and medical judgements pass through an authorised clinician.
2. **Never invent.** Only assemble what was documented — no unrecorded findings, treatments or improvements.
3. **Show the evidence.** Every alert and draft line links back to its source.
4. **Know said from ordered from done.** A discussion is not an order, a prescription is not an administration, a task is not a completion.
5. **Integrate, do not replace.** The hospital keeps its HMS and EMR; MediBytes connects by API.

Alert precision is a product requirement. Too many false alarms and clinicians ignore the system; too few alerts and they trust it wrongly.

## Commercial model

A recurring platform subscription for the modules enabled, plus AI credits consumed per operation. The illustrative schedule: OCR 1, voice note 2, medicine reconciliation 2, report analysis 4, discharge summary 5, with monthly packs of 5,000, 15,000 and 50,000. These are proposed units, not final prices.

## Glossary

| Term | Meaning |
| --- | --- |
| HMS | Hospital Management System: patients, beds, billing, departments |
| EMR | Electronic Medical Record: the digital patient file |
| OCR | Reading text from scanned pages and photographs |
| TPA | Third-Party Administrator: administers insurance claims for an insurer |
| eGFR | Kidney function, mL/min/1.73 m²; lower is worse |
| Reconciliation | Comparing two versions of a record and resolving the differences |
| Closed loop | A decision tracked from recorded to completed and accounted for |

## Open questions

- [ ] Acceptable false-positive rate per Guardrail check, and how it is measured in pilot
- [ ] Billing unit for one OCR credit: page or document
- [ ] Baseline metrics a pilot hospital must capture before go-live
- [ ] Minimum viable first release, given that F16 underpins F5, F9 and F14
- [ ] Fallback behaviour when an integration drops mid-shift
