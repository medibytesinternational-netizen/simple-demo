# Revenue Leakage: wireframe (revision 3)

Route unchanged: `/revenue?tab=leakage` (Admin only). It moves from inline JSX in `pages/Revenue.tsx` to `features/f13/LeakageView.tsx`.

> **How to read the numbers in this document**
> - `{field}` is a **runtime binding** to the API ([KPI data contract](moscow-prioritization.md#3-kpi-data-contract-runtime-bindings-nothing-hardcoded)). The page renders whatever the API returns.
> - `e.g. …` is an **illustrative example**, taken from the snapshot below. It is never hardcoded.
> - The **Worked example** section is the only place where values are quoted as actual API output, with the time they were captured.
>
> Revision 3: the bed-days figures were consistent but shown without the subtraction step, so *expected* (INR 126,000) and *gap* (INR 118,000) looked contradictory. Every bed-days figure now shows **expected − billed = gap**, and the worked example below reconciles all totals.

## Worked example: actual API values (snapshot)

Captured from `GET /revenue/leakage` and `GET /meta` on the throwaway QA database at demo clock **2026-11-23 17:12**. Encounter `enc_ipd_1` admitted **2026-10-18 14:10**, not discharged.

| # | Finding (`kind` / `service_kind` / `code`) | Calculation from API fields | `variance` (gap) | In total? | Estimate? |
|---|---|---|---|---|---|
| 1 | unbilled / procedure / 97597 Wound debridement | expected 1 × 3,500 = 3,500 − billed 0 | **3,500** | yes | no |
| 2 | underbilled / bed_day / ROOM2 Bed-days | expected **36 days × 3,500 = 126,000** − billed **8,000** | **118,000** | yes | **yes** (open admission) |
| 3 | underbilled / medication / J01 IV antibiotics | expected 4,200 − billed 3,200 | **1,000** | yes | no |
| 4 | underbilled / procedure / PT01 Physiotherapy | expected 2,400 − billed 1,200 | **1,200** | yes | no |
| 5 | unsupported / procedure / PT01 Physiotherapy | billed 1,200 with no documentation | — | no (compliance) | no |

Reconciliation (all in INR):

| Figure on the page | Formula | Value |
|---|---|---|
| Revenue at risk | `leakage_amount` from the API | **123,700** |
| check: sum of gaps for findings 1–4 | 3,500 + 118,000 + 1,000 + 1,200 | 123,700 ✓ |
| Open-admission estimate | Σ `variance` where `service_kind = bed_day` and not discharged = finding 2 | **118,000** |
| Billing discrepancies | `leakage_amount` − estimate = 123,700 − 118,000 (= 3,500 + 1,000 + 1,200) | **5,700** |
| Root cause: Documented, not billed | finding 1 | 1 · **3,500** |
| Root cause: Billed below tariff | findings 2 + 3 + 4 = 118,000 + 1,000 + 1,200 | 3 · **120,200** (incl. 118,000 estimate) |
| Root cause: Quantity mismatch | none | 0 |
| Root cause: Billed without documentation | finding 5, `billed_amount` | 1 · **1,200** (not in total) |
| check: root causes in total | 3,500 + 120,200 + 0 | 123,700 ✓ |
| By service type: Bed-days | finding 2 | 118,000 (estimate) |
| By service type: Procedure | findings 1 + 4 = 3,500 + 1,200 | 4,700 |
| By service type: Medication | finding 3 | 1,000 |
| check: service types | 118,000 + 4,700 + 1,000 | 123,700 ✓ |

**These values change over time.** While the admission is open, the backend adds one bed-day every 24 hours after 14:10. At 37 days the bed-days expected amount would be 129,500, its gap 121,500, and the total 127,200. The page always shows the live API values with their calculation. The snapshot is only for this document.

## Current vs proposed

| Current | Proposed |
|---|---|
| A flat list of text rows; no money shown | **Revenue at risk hero**, split into billing discrepancies and open-admission estimate, plus a root-cause breakdown |
| Every finding looks the same | Findings sorted by gap, each showing **Expected − Billed = Gap** with a comparison bar |
| Explanation sentence is the only detail | **Detail drawer**: calculation, explanation, evidence, references |
| No grouping | **Root-cause cards** and **service-type bars**, both acting as filters |
| No export | **Export CSV** and **Print** (browser) |

## Root-cause categories (from the API)

| Source field | Category label | In "at risk" total? |
|---|---|---|
| `kind: "unbilled"` | Documented, not billed | yes: gap = `variance` |
| `kind: "quantity_mismatch"`, `billing_status: "underbilled"` | Quantity mismatch: fewer billed | yes |
| `kind: "quantity_mismatch"`, `billing_status: "unsupported"` | Quantity mismatch: more billed than documented | no (compliance) |
| `kind: "underbilled"` | Billed below tariff | yes |
| `kind: "unsupported"` | Billed without documentation | no: separate compliance amount = `billed_amount` |

This mirrors the backend's `leakage_amount` (sum of `variance` for unbilled and underbilled findings). The page **shows the API total as returned**. The category, service-type and estimate figures are sums of the same findings' `variance`, so they always add up to it (see the checks above). If they ever didn't (e.g. a future backend change), the page would show the API total and a "breakdown does not match the total" note, not an adjusted figure.

## Open-admission estimate

**When:** a finding has `service_kind === "bed_day"` and `GET /meta` → `encounter.discharged_at` is empty. The backend then counts whole bed-days from `admitted_at` to the current clock.

**How it looks (frontend only; the finding is not excluded or altered, and the backend is unchanged):**
- Card and row get an **"Estimate · open admission"** badge and a **dashed amber outline** instead of a solid stripe.
- The full calculation is always shown, in this order:
  1. **Expected** `{documented_quantity} days × {unit_price} = {expected_amount}` (e.g. 36 days × INR 3,500 = INR 126,000)
  2. **Billed** `{billed_amount}` (e.g. INR 8,000)
  3. **Estimated gap** `{variance}` (e.g. INR 118,000)
  4. "Counted from admission `{admitted_at}` to today; not yet discharged."
- The hero shows the API total and its split, both labelled as gaps (expected − billed):
  - **Billing discrepancies** = `leakage_amount` − estimate
  - **Open-admission estimate** = Σ `variance` of the estimate findings
- In "By service type", the bed-days bar is hatched and labelled "estimate".
- Once `discharged_at` is set, the same finding renders as an ordinary discrepancy, without the badge.
- If `documented_quantity`, `unit_price`, `billed_amount` or `admitted_at` is missing, the calculation line says which value is unavailable and the gap is shown only as returned in `variance`. Nothing is guessed.

## Desktop (≥ 1180px), live data

All INR figures below are illustrative (`e.g.`) from the snapshot.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Revenue leakage                                  [⇩ Export CSV] [⎙ Print]    │ ← COULD (secondary)
│ {encounter.kind} · admitted {admitted_at} · {discharged_at or "not discharged"}│
│ ⓘ Review only: nothing on this page changes the bill or the claim            │
├────────────────────────────────┬─────────────────────────────────────────────┤
│▓ REVENUE AT RISK              ▓│ BY ROOT CAUSE (gaps)              filters   │
│▓ {leakage_amount}             ▓│ ┌────────────────┐┌─────────────────┐       │
│▓   e.g. INR 123,700           ▓│ │Documented,     ││Billed below     │       │ ← SHOULD
│▓ Gaps = expected − billed     ▓│ │not billed      ││tariff           │       │
│▓ ───────────────────────────  ▓│ │{n} · {Σgap}    ││{n} · {Σgap}     │       │
│▓ Billing discrepancies        ▓│ │e.g. 1 · 3,500  ││e.g. 3 · 120,200 │       │
│▓   e.g. INR 5,700             ▓│ └────────────────┘│incl. e.g. 118,000│      │
│▓ Open-admission estimate ┄┄┄  ▓│                   │estimate         │       │
│▓   e.g. INR 118,000  ESTIMATE ▓│ ┌────────────────┐└─────────────────┘       │
│▓ ───────────────────────────  ▓│ │Quantity        │┌─────────────────┐       │
│▓ {count} findings  e.g. 5     ▓│ │mismatch {n}    ││Billed without   │       │
│▓ + {Σ unsupported billed}     ▓│ │e.g. 0          ││documentation    │       │
│▓   e.g. INR 1,200 billed      ▓│ └────────────────┘│{n} · {Σbilled}  │       │
│▓   without documentation      ▓│                   │e.g. 1 · 1,200   │       │
│▓   (compliance, not in total) ▓│                   │not in total     │       │
└────────────────────────────────┴───────────────────┴─────────────────┴───────┘

┌──────────────────────────────────────────────────────┬───────────────────────┐
│ FINDINGS {count}     [All types ▾]  🔍 Search services│ EXPLAIN               │
│ By service type (Σ gap per service_kind):            │ [✦ Explain findings ] │ ← PRIMARY (revenue_work)
│   Bed-days   ▨▨▨▨▨▨▨▨▨▨▨▨▨▨ e.g. 118,000 estimate    │ Drafts a short review │
│   Procedure  █ e.g. 4,700                            │ note from these       │
│   Medication ▏e.g. 1,000                             │ findings.             │
├──────────────────────────────────────────────────────┤├──────────────────────┤
│▌NOT BILLED  {procedure} · {code}    Gap {variance}   ││ F13 DraftReview      │
│▌  e.g. Wound debridement · 97597    e.g. 3,500       ││ (approve / edit),    │
│▌Expected {expected} ████  Billed {billed}  Details › ││ or empty state       │
│▌  e.g. 3,500 − 0 = 3,500 · evidence {n}              │├──────────────────────┤
├──────────────────────────────────────────────────────┤│ HOW THIS IS COMPUTED │
│▌BELOW TARIFF  e.g. Physiotherapy · PT01  Gap e.g. 1,200││ (existing text) +   │
│▌  e.g. 2,400 − 1,200 = 1,200                         ││ "Open admissions are │
│▌BELOW TARIFF  e.g. IV antibiotics · J01  Gap e.g. 1,000││ counted to today"   │
│▌  e.g. 4,200 − 3,200 = 1,000                         │├──────────────────────┤
├──────────────────────────────────────────────────────┤│ Review only. Fix the │
│┆ESTIMATE · OPEN ADMISSION   e.g. Bed-days · ROOM2   ┆││ bill in the billing  │
│┆Expected {qty} days × {unit_price} = {expected}     ┆││ system.              │
│┆  e.g. 36 days × INR 3,500 = INR 126,000            ┆│└──────────────────────┘
│┆Billed {billed_amount}          e.g. INR 8,000      ┆│
│┆Estimated gap {variance}        e.g. INR 118,000    ┆│
│┆Counted from {admitted_at} to today; not discharged ┆│
│┆evidence {n}                              Details › ┆│
├──────────────────────────────────────────────────────┤
│▌NO DOCUMENTATION  e.g. Physiotherapy · PT01          │
│▌Billed {billed_amount} e.g. 1,200 · no gap figure    │
│▌(red stripe; compliance, not revenue)                │
├──────────────────────────────────────────────────────┤
│ ▸ Services not checked (unmapped) {n}      folded    │
└──────────────────────────────────────────────────────┘
```
Sort: confirmed discrepancies by gap (largest first), then estimates, then compliance findings. An estimate never outranks confirmed gaps just because the clock has moved on.

## Finding detail drawer (SHOULD)

```
┌────────────── {procedure} · {code} ──────────── ✕ ┐
│ BILLED BELOW TARIFF   ┆ESTIMATE · OPEN ADMISSION┆ │
│ Expected  {qty} × {unit_price} = {expected}      │  e.g. 36 × 3,500 = 126,000
│ Billed    − {billed_amount}                      │  e.g. − 8,000
│ ───────────────────────────────────              │
│ Estimated gap  = {variance}                      │  e.g. = 118,000
│ Basis: whole bed-days from admission             │
│ {admitted_at} to today; not yet discharged.      │
│ Becomes a confirmed figure once discharged.      │
│                                                  │
│ Why: "{explanation}"                             │ ← API text, verbatim
│ Evidence: [chips from evidence_event_ids]        │
│ References: {evidence_refs}                      │
│ ──────────────────────────────────────────────── │
│ Review only. This page does not change the bill. │
└──────────────────────────────────────────────────┘
```
For non-estimate findings: the same layout labelled "Gap", without the estimate badge and basis lines. For unsupported findings: "Billed {billed_amount}, no supporting documentation", with no gap line. Phone: full-screen sheet.

## Phone (< 768px)

```
┌──────────────────────────────┐
│ Revenue leakage              │
│ ⓘ Review only                │
│▓ REVENUE AT RISK            ▓│
│▓ {leakage_amount}           ▓│
│▓ discrepancies {x}          ▓│
│▓ estimate {y} ┄ ESTIMATE    ▓│
│[✦ Explain findings        ]  │ primary
│ [Not billed {n}] [Below {n}] │ chips, horizontal scroll
│ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐ │
│ ┆ESTIMATE · {procedure}     ┆ │ finding cards
│ ┆Expected {qty}×{rate}      ┆ │
│ ┆  = {expected}             ┆ │
│ ┆Billed {billed}            ┆ │
│ ┆Est. gap {variance}        ┆ │
│ ┆[Details ›]                ┆ │
│ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘ │
│ [Export CSV] [Print]         │
│ F13 explanation · method     │
└──────────────────────────────┘
```
Tablet: hero and root-cause grid stack; the rail goes under the findings.

## DEMO mode (fixture lacks amounts)

The DEMO fixture has 4 findings with only `id`, `procedure`, `billing_status`, `explanation`, `evidence_event_ids`. There is no `leakage_amount`, `kind`, `code`, `service_kind`, quantities or amounts, and no F13 draft.

```
┌────────────────────────────────┬─────────────────────────────────────────────┐
│▓ REVENUE AT RISK              ▓│ BY ROOT CAUSE (counts only)                 │
│▓   —                          ▓│ [Documented, not billed {n}]  (fixture: 1)  │
│▓ Amount unavailable in preview▓│ [Billed below tariff or short quantity {n}] │
│▓ {count} findings (fixture: 4)▓│                                (fixture: 2) │
│▓                              ▓│ [Billed without documentation {n}] (fixt.: 1)│
└────────────────────────────────┴─────────────────────────────────────────────┘
 FINDINGS {count}
 ▌NOT BILLED  {procedure}                                        Details ›
 ▌Amount unavailable in preview · "{explanation}" · evidence
```
- Categories come from `billing_status`. "Quantity mismatch" can't be told apart from "below tariff" without `kind`, so in DEMO they share one card, labelled as such.
- No service-type section, no compare bars, no estimate split, no calculation lines (no data to base them on). There are no empty charts.
- The drawer shows the explanation and evidence, plus "Amounts unavailable in preview".
- Export CSV works; amount columns are left blank (not 0).
- Explain findings is refused with the existing preview message; the F13 panel shows its empty state.

## Export (COULD)
- **CSV**: one row per loaded finding: category, estimate (yes/no), service, code, service type, documented qty, billed qty, unit price, expected, billed, gap, explanation, evidence ids. Values are copied from the API as returned; missing values are left blank, not 0. Built in the browser.
- **Print**: `window.print()` with a print stylesheet that hides the navigation, rail and buttons, and prints the hero (with the estimate split and a timestamp), breakdown and all findings expanded, including calculation lines.

## Behaviour preserved
- `Explain findings` → `POST /revenue/leakage/explain`, then `DraftReview` for F13 (edit / approve / reject unchanged).
- Evidence chips open the existing evidence viewer; "How this is computed" text kept.
- No Resolve / Add to bill / Add to claim / Exclude controls (no backend support; approved decision).

## Data (unchanged API; additive TS type)
`GET /revenue/leakage` → `leakage_amount`, `count`, `summary`, `unmapped_services[]`, `findings[]` (`id`, `kind`, `billing_status`, `procedure`, `code`, `service_kind`, `unit_price`, `documented_quantity`, `billed_quantity`, `expected_amount`, `billed_amount`, `variance`, `documented_as`, `explanation`, `evidence_event_ids`, `evidence_refs`). `GET /meta` → `encounter.admitted_at`, `encounter.discharged_at`.
