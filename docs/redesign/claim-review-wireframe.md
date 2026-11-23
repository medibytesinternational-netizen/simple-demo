# Claim Review: wireframe (revision 2)

Route unchanged: `/revenue?tab=claim` (Admin only). It moves from inline JSX in `pages/Revenue.tsx` to `features/f12/ClaimReview.tsx`.

> Values in `{braces}` are runtime bindings ([KPI data contract](moscow-prioritization.md#3-kpi-data-contract-runtime-bindings-nothing-hardcoded)). INR figures next to them are **examples** from the seeded encounter, not fixed values.

## Current vs proposed

| Current | Proposed |
|---|---|
| A 4-stat summary strip that looks like every other strip | A **readiness hero** (status, TPA status, blocker count) plus **financial KPI cards** |
| Status is a small pill inside the Required documents panel | Status is the **first thing on the page** |
| Blockers spread over 5 panels of equal weight | **One Blockers zone**, ranked, each with "Fix in…" or evidence |
| Prepare / Open copy / Explain in a toolbar above everything | An **action rail** card with one primary action |
| Full bill and duplicate unbilled tables always open | Bill tables **folded**; "Documented but unbilled" **removed** and replaced by a link to Revenue leakage |
| No coding information | **Coding checks** card stating what is and isn't checked |

## Status model

The backend has exactly two status fields plus a list of prepared packs. The page shows them as three separate indicators so they can't be confused.

| Indicator | Backend field | Values → display |
|---|---|---|
| **Claim readiness** (the hero) | `status` | `needs_clarification` → red ⛔ **Clarification required** · `on_hold` → amber ⏸ **On hold** · `review_ready` → green ✓ **Ready for human review** |
| **TPA review** (chip in the hero and the rail) | `tpa_review.status` | `needs_clarification` → red-outlined chip **"TPA review: needs clarification"** · `ready_for_review` → green-outlined chip **"TPA review: ready"** |
| **Review pack** (chip in the header) | `reviews[0]` | none → **"Review pack: not prepared"** · otherwise **"Pack {id} · prepared {prepared_at} · {status at that time}"** |

How the backend derives them (from `claims.py`), and what each combination looks like:

| `status` | `tpa_review.status` | Cause | Hero |
|---|---|---|---|
| `needs_clarification` | `needs_clarification` | ≥ 1 contradiction | red hero + red TPA chip; contradictions listed first |
| `on_hold` | `ready_for_review` | no contradictions, but missing documents or unsupported bill lines | amber hero + **green** TPA chip: the TPA review itself isn't blocked, the documents are |
| `review_ready` | `ready_for_review` | nothing blocking | green hero, "Nothing is blocking human review. Nothing is submitted." |

**Not shown:** Approved, Rejected, Pending or Submitted. They don't exist in the backend. An unknown future value renders as a neutral grey hero with the raw value in words, never mapped to an invented state.

## Desktop (≥ 1180px)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Claim review                                    ⓘ Review only · no submission │
│ {encounter.kind} · {ward} · {bed} · admitted {admitted_at}                   │
│ [Review pack: not prepared]                                                  │ ← pack chip ({reviews[0]})
├──────────────────────────────────────────────────────────────────────────────┤
│▌⛔ CLARIFICATION REQUIRED                       [TPA review: needs clarification]│ ← readiness hero + TPA chip
│▌ {blockers} items block this claim from human review           e.g. 6        │
│▌ {contradictions} contradictions · {missing} missing documents ·             │
│▌ {unsupported} bill lines without documentation         [Jump to blockers ↓] │
├───────────────────┬───────────────────┬───────────────────┬─────────────────┤
│▓ BILL TOTAL      ▓│ EXPECTED TOTAL    │ BELOW EXPECTED    │ DOCUMENTS        │ ← MUST: financial
│▓ {total_amount}  ▓│ {expected_total_  │ {underbilled_     │ {present} of     │   summary
│▓  e.g. INR 13,900▓│  amount}          │  amount}          │ {required}       │
│▓ {billed_items.  ▓│  e.g. INR 16,100  │  e.g. INR 2,200   │  e.g. 2 of 4     │
│▓  length} lines  ▓│ from bill lines'  │ {n} lines below   │ ██████░░░░░░     │
│▓                 ▓│ expected amounts  │ expected          │                  │
└───────────────────┴───────────────────┴───────────────────┴─────────────────┘
   No "approved amount" card: the data has no such field.

┌──────────────────────────────────────────────────────┬───────────────────────┐
│ BLOCKERS  {blockers}                                 │ ACTIONS               │
│                                                      │ [ Prepare review pack]│ ← PRIMARY (revenue_work)
│ ● Contradictions  {n}                     CRITICAL   │ [⇗ Open review copy ] │
│ ┌──────────────────────────────────────────────────┐ │ [✦ Explain gaps     ] │
│ │▌{title}                                          │ │ Nothing is sent to    │
│ │▌{kind} · {evidence.length} sources  Show sources ▾│ │ the payer.            │
│ │▌ "{evidence[0].quote}"  vs  "{evidence[1].quote}"│ ├───────────────────────┤
│ └──────────────────────────────────────────────────┘ │ TPA REVIEW            │
│                                                      │ [needs clarification] │
│ ● Missing documents  {n}                  BLOCKS     │ {n} contradictions    │
│ │▌Signed discharge summary        [Fix in Discharge ›]│ {n} missing documents │
│ │▌Pre-authorisation approval  [Fix in Records follow-up ›]│ Review history:   │
│                                                      │ {reviews} or "No packs│
│ ● Bill lines without documentation  {n}              │ prepared"             │
│ │▌{code} {description} · {amount}         evidence › │├───────────────────────┤
├──────────────────────────────────────────────────────┤ CLAIM EXPLANATION     │
│ REQUIRED DOCUMENTS        {present} of {required} ███│ F12 DraftReview, or   │ ← SHOULD
│ ✓ / ✗ {label}            evidence / Fix ›            │ empty state           │
├──────────────────────────────────────────────────────┤                       │
│ CODING CHECKS                                        │                       │ ← SHOULD (limited)
│ ✓/✗ Documented procedures with a code ({n} of {m})   │                       │
│ ✓/✗ Bill lines with a supporting record ({n} of {m}) │                       │
│ ⓘ Diagnosis (ICD) codes are not checked by this      │                       │
│   system and can't be edited here.                   │                       │
├──────────────────────────────────────────────────────┤                       │
│ BILLING DISCREPANCIES                                │                       │
│ Line            Billed       Expected     Gap        │ ← underbilled_items
│ {code} {desc}   {billed} ██  {expected} ███ {variance}│  (CompareBar)
│ ┌ Revenue gaps against the tariff are reviewed on    ┐│ ← replaces "Documented
│ └ Revenue leakage.                  [Open Revenue leakage ›]┘│   but unbilled"
├──────────────────────────────────────────────────────┤                       │
│ ▸ Patient bill ({n} lines, {total_amount})  folded   │ ← detail
│ ▸ Documented procedures ({n})               folded   │                       │
└──────────────────────────────────────────────────────┴───────────────────────┘
```

"Fix in…" links point only to existing pages: Signed discharge summary → `/discharge`; Pre-authorisation approval → `/documents?tab=followup`; Laboratory reports → `/notes?tab=labs`. The Itemized bill has no in-app fix, so it shows evidence only.

## Phone (< 768px)

```
┌──────────────────────────────┐
│ Claim review   ⓘ Review only │
│▌⛔ CLARIFICATION REQUIRED    │ hero first
│▌[TPA review: needs clarif.]  │
│▌{blockers} items block review│
│[  Prepare review pack     ]  │ primary right after the hero
│[Open copy]   [Explain gaps]  │
├──────────────┬───────────────┤
│▓BILL {total}▓│ EXPECTED {exp}│ KPI 2×2
│ BELOW {under}│ DOCS {n} of {m}│
├──────────────┴───────────────┤
│ BLOCKERS (cards, full width) │
│ REQUIRED DOCUMENTS           │
│ CODING CHECKS                │
│ BILLING DISCREPANCIES (cards)│
│ ▸ Patient bill               │
│ TPA review · Explanation     │ rail content last
└──────────────────────────────┘
```
Tablet: KPI 2 × 2; the action rail becomes a horizontal action bar under the hero; other rail cards go under the main column.

## DEMO mode
- The fixture has complete claim data, so the hero, TPA chip and all four KPI cards are populated from it (no unavailable states expected). If a future fixture lacks a field, that card shows "—" and "Amount unavailable in preview".
- Contradictions in the fixture have **no evidence quotes**, so cards show evidence chips (the existing `ContradictionList` fallback) instead of quotes.
- `reviews` is empty, so the chip reads "Review pack: not prepared" and the history reads "No packs prepared".
- No F12 draft, so the explanation panel shows its empty state.
- Prepare review pack and Explain gaps are refused with the existing preview message. Open review copy opens the static preview copy (existing behaviour).

## Behaviour preserved
- `Prepare review pack` → `POST /revenue/claim-prep/prepare`, with the same success banner ("Review clm_… is …; nothing was submitted").
- `Open review copy` → `openApiWindow("/revenue/claim-prep/pack.html")`.
- `Explain gaps` → `POST /revenue/claim-prep/explain`, then `DraftReview` for F12.
- `ContradictionList` evidence, `TpaState` facts, required-document evidence, unsupported lines, review history: all kept, regrouped.
- Without `revenue_work`: action buttons are replaced by "Read only for your role" (existing). Navigation still limits the page to Admin.

## States
- Loading: skeleton hero and KPI cards. Error: red banner instead of the hero; KPI values "—".
- `review_ready`: green hero; the Blockers zone collapses to one success line.

## Data (unchanged API)
`GET /revenue/claim-prep` → `status`, `required_documents`, `missing_documents`, `contradictions[]` (optional `evidence[]` quotes), `unsupported_items`, `underbilled_items`, `billed_items`, `documented_procedures`, `tpa_review`, `total_amount`, `expected_total_amount`, `underbilled_amount`, `discharge_signed`, `reviews[]`. Encounter context from `GET /meta`.
No longer rendered here: `unbilled_procedures` (the duplicate; Revenue leakage covers it).
