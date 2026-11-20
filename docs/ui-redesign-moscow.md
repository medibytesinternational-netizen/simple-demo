# MoSCoW UI redesign — Lab results, Claim review, Revenue leakage

Frontend-only redesign of three existing views. Routes, navigation, APIs and the backend are unchanged.

| View | Route | Main file |
|---|---|---|
| Lab results | `/notes?tab=labs` | `frontend/src/features/labs/LabResults.tsx` (rendered by `pages/Notes.tsx`) |
| Claim review | `/revenue?tab=claim` | `frontend/src/pages/Revenue.tsx`, `features/f12/*` |
| Revenue leakage | `/revenue?tab=leakage` | `frontend/src/pages/Revenue.tsx`, `features/f13/*` |

There is no separate "Revenue Package" page; the Revenue leakage tab is that workflow.

## Shared colour rules

| Meaning | Tone |
|---|---|
| Critical lab value, claim blocker, "Flagged" claim, billed without documentation | `critical` (red) |
| High / low lab value, "Pending" (on hold) claim, unbilled or billed-below-tariff amount | `warning` (amber) |
| Normal value, document present, "Ready for review" | `success` (green) |
| Not flagged / unknown | `neutral` |

One accent (primary) button per view. Secondary actions sit in a "More" menu, a filter or a collapsed section.

## 1. Lab results

| | Feature | Data source |
|---|---|---|
| MUST | Abnormal and unreviewed results first ("Needs review") | `GET /investigations` |
| MUST | Severity pill per result: Critical, High, Low, Normal, Not flagged | `flag` |
| MUST | Reference range; "Not reported" when missing | `reference_range` |
| MUST | Mark reviewed inline on every unreviewed abnormal result | `POST /labs/{id}/review` |
| SHOULD | Filters: All / Abnormal / Unreviewed; search by test name | client side |
| SHOULD | Grouped by panel (Renal, Diabetic, Infection & inflammation, ...) | fixed name map in `features/labs/panels.ts` |
| SHOULD | Mark all normal results reviewed | repeated calls to the existing per-result endpoint |
| COULD | Trend arrow and previous value; the Trend column appears only when an earlier result exists | `GET /patients/{id}/timeline?types=lab_result` |
| WON'T | Predictive diagnosis, decision support | — |

```
Lab results                                               (page header + Notes tabs)
[All 6 | Abnormal 6 | Unreviewed 1]  [Search test…]   5 of 6 reviewed   [Upload lab report]
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ NEEDS REVIEW (1)                                                                      │
│ Renal                                                                                 │
│  [High] Creatinine   2.9 mg/dL   0.7 - 1.3   ↑ from 2.1   19 Oct 06:00  [Mark reviewed] │
│ ABNORMAL · REVIEWED (5)                                                               │
│ Renal      [Low] eGFR 22 …                                              ✓ Reviewed    │
│ Diabetic   [High] HbA1c 8.4 % …                                         ✓ Reviewed    │
│ NORMAL & NOT FLAGGED (n)                                   [Mark n normal reviewed]   │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Claim review

| | Feature | Data source |
|---|---|---|
| MUST | Claim status: Ready for review / Pending (on hold) / Flagged (needs clarification) | `status`, `tpa_review.status` |
| MUST | Bill total, expected total, billed below tariff; unbilled items are listed separately in Revenue leakage | `total_amount`, `expected_total_amount`, `underbilled_amount` |
| MUST | Blockers on top: missing documents, contradictions, billed lines without documentation | claim-prep lists |
| MUST | One primary action: Prepare review pack | `POST /revenue/claim-prep/prepare` |
| SHOULD | Required-documents checklist (Present / Missing); each missing-document blocker has a "Go to Documents" or "Go to Discharge" link | `required_documents` |
| SHOULD | Bill lines with codes; validation shown on the line ("No documentation", "−INR n vs tariff") | `billed_items`, `underbilled_items` |
| SHOULD | Compact "Billing gaps" summary linking to Revenue leakage; undocumented lines are referred to Blockers, not repeated | counts and amounts |
| — | Review history, documented procedures, gap explanation draft: collapsed sections | existing |
| Not possible | Approved / Rejected states, approved amount, code editing, risk score, payer history | not in the API |
| WON'T | Payer submission, AI claim prediction | — |

```
Claim review                                  (page header + Claim review / Revenue leakage tabs)
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ [● Flagged] TPA: needs clarification          [Prepare review pack]  [More ▾]        │
│ Bill total INR 48,200   Expected total INR 52,400   Billed below tariff INR 4,200    │
│                         Unbilled items are listed separately in Revenue leakage      │
└──────────────────────────────────────────────────────────────────────────────────────┘
┌ Blockers before review (3) ──────────────────────────────────────────────────────────┐
│ ✕ Pre-authorization approval  [Missing document]                 [Go to Documents]   │
│ ✕ Contradiction: …                                                                   │
│     ▸ Sources (2)                                                                    │
│ ✕ Physiotherapy session  [Billed without documentation]           INR 2,400          │
└──────────────────────────────────────────────────────────────────────────────────────┘
Required documents (checklist)      │  Bill lines (code · item · amount · documentation)
Billing gaps: 1 documented but unbilled · 2 billed below tariff (INR …) ·
              Undocumented bill lines are listed under Blockers.   View in Revenue leakage ›
▸ Review history   ▸ Documented procedures   ▸ Gap explanation (draft)
```

## 3. Revenue leakage

| | Feature | Data source |
|---|---|---|
| MUST | Total not billed (INR) | `leakage_amount` |
| MUST | Each missing item with code and amount | `findings[].variance`, `code` |
| MUST | Primary action: Prepare review pack, labelled so it does not suggest the bill changes | `POST /revenue/claim-prep/prepare` |
| SHOULD | Department filter: Lab & imaging, Pharmacy, Ward / ICU, Procedures, Consults | `findings[].service_kind` |
| SHOULD | Root cause per item: ordered/given/performed but not billed, quantity mismatch, billed below tariff | `findings[].kind`, `documented_as` |
| SHOULD | Billed without documentation listed separately and not counted in the total | `billing_status = unsupported` |
| COULD | Export CSV (More menu) | built in the browser from loaded findings |
| — | Unmapped services, method note, explanation draft: collapsed | existing |
| Not possible | Consumables category, package-exclusion cause, adding items to the bill | not in the tariff or API |
| WON'T | Cross-hospital analytics, AI revenue prediction | — |

```
Revenue leakage
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ INR 11,900 not billed · 4 items · 1 billed without documentation                     │
│                                              [Prepare review pack]  [More ▾]         │
│ Preparing a review pack records these gaps for human review. It does not add items   │
│ to the bill or change the claim.                                                     │
└──────────────────────────────────────────────────────────────────────────────────────┘
[All · 11,900 | Pharmacy · 4,200 | Ward / ICU · 3,500 | Lab & imaging · 2,200 | …]
┌ Missing from the bill ───────────────────────────────────────────────────────────────┐
│ Item (code)            Department    Cause                        Gap         Source │
└──────────────────────────────────────────────────────────────────────────────────────┘
┌ Billed without documentation (not in the total) ─────────────────────────────────────┐
│ Item (code)  "Same code is also in Missing from the bill" when it appears in both    │
└──────────────────────────────────────────────────────────────────────────────────────┘
▸ Services with no tariff code   ▸ How this is computed   ▸ Findings explanation (draft)
```
