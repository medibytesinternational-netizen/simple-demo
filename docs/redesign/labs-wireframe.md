# Lab Results: wireframe (revision 2)

Route unchanged: `/notes?tab=labs`, rendered by `features/labs/LabResults.tsx`.

> Values in `{braces}` are runtime bindings ([KPI data contract](moscow-prioritization.md#3-kpi-data-contract-runtime-bindings-nothing-hardcoded)). Numbers next to them are **examples** from the fresh QA seed, not fixed values.

## Current vs proposed

| Current (Stage 2) | Proposed |
|---|---|
| Header → one-sentence banner → one panel of four small tables | Header → **4 KPI cards** → **"Needs your review" card grid** → results workspace with rail |
| Abnormal = amber text in a table row | Abnormal = a **card** with big value, flag badge, reference text, a range bar *where reliable*, and its own Mark reviewed button |
| Reference range = text column | Original text **always**; a bar only when it is safe (rules below) |
| Normal results = a table section | A **compact, quiet group**, folded once reviewed |
| No history | **Previous value and change**, only when real earlier results exist |

## Desktop (≥ 1180px)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Lab results                                            [⇪ Upload lab report] │ ← secondary CTA
│ Latest result per test · last collected {max(collected_at)}                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ (upload / OCR message appears here only after an upload: unchanged wording)  │
├───────────────────┬──────────────────┬──────────────────┬───────────────────┤
│▓ PENDING REVIEW  ▓│ ABNORMAL         │ CRITICAL         │ TOTAL TESTS       │ ← MUST: overview
│▓ {unreviewed}    ▓│ {abnormal}       │ {critical}       │ {labs.length}     │
│▓   e.g. 1        ▓│   e.g. 6         │   e.g. 0         │   e.g. 6          │
│▓ {n} abnormal ·  ▓│ {n} reviewed     │ 0 → "None flagged│ {reviewed_count}  │
│▓ {n} normal      ▓│                  │ critical by the  │ reviewed          │
│▓                 ▓│                  │ source"          │                   │
└───────────────────┴──────────────────┴──────────────────┴───────────────────┘

 NEEDS YOUR REVIEW  {count}                               abnormal or unflagged
┌─────────────────────────────────────┐ ┌──────────────────────────────────────┐
│▌Creatinine                ▲ HIGH    │ │ (2 per row; critical cards first,    │
│▌ 2.9 mg/dL                          │ │  red stripe + tint; "Not flagged"    │
│▌ Reference 0.7 – 1.3                │ │  cards last, grey stripe)            │ ← original text, always
│▌ ┄┄┄┄[▓▓▓▓ range ▓▓▓▓]┄┄┄┄┄┄┄┄▶      │ │                                      │ ← bar only if rules pass
│▌ Collected 19 Oct, 06:00            │ │                                      │
│▌ Previous 2.4 · 18 Oct   ▲ +0.5     │ │                                      │ ← COULD: real history only
│▌ [ ✓ Mark reviewed ]   History ›    │ │                                      │ ← PRIMARY CTA (role-gated)
└─────────────────────────────────────┘ └──────────────────────────────────────┘
 (when nothing is waiting: one slim green strip, "Nothing waiting for review")

┌──────────────────────────────────────────────────────┬───────────────────────┐
│ ALL RESULTS                                          │ REVIEW PROGRESS       │
│ [All {n}][Abnormal {n}][Unreviewed {n}] 🔍 Search    │ ███████████░░ {r}/{t} │
├──────────────────────────────────────────────────────┤ reviewed              │
│ Abnormal · reviewed  {n}                             ├───────────────────────┤
│ CRP          92 mg/L    Ref 0 – 5   ┄[▓▓]┄┄┄┄┄▶ ▲High ✓│ HOW FLAGS WORK      │
│ eGFR         22 mL/min  Ref > 90                ▼Low  ✓│ High / Low / Normal │
│              (one-sided range: text only)       │ come from the lab     │
│ Potassium    5.1 mmol/L Ref 3.5 – 5.1           ▲High ✓│ report or record.   │
│              (bar would contradict flag: text only) │ Critical appears    │
│ HbA1c        8.4 %      Ref 4.0 – 5.6 ┄[▓▓]┄┄┄▶ ▲High ✓│ only when the       │
│ White cells  13.8       Ref 4.0 – 11.0 ┄[▓▓]┄●┄ ▲High ✓│ source sends it.    │
├──────────────────────────────────────────────────────┤ Range bars are drawn │
│ Normal · awaiting review {n}   [✓ Review all normal] │ only from numeric     │ ← SHOULD: bulk (role-gated)
│ ▸ Reviewed, normal or not flagged {n}   (folded)     │ two-sided ranges.     │
└──────────────────────────────────────────────────────┴───────────────────────┘
```

## Reference-range bar rules

The **API `flag` is the only source of severity**. The bar is a visual aid for comparing the value with the range text the API supplied. It never decides anything.

A bar is drawn **only if all** of these hold; otherwise the original `reference_range` text is shown alone:

1. `reference_range` parses (existing `parseRange`) to **both** a low and a high number, with `low < high`. One-sided (`> 90`, `< 5`), free text ("see report", "negative"), or empty → **text only**.
2. `value` is a plain finite number (`"2.9"`, `13.8`). Values such as `"<0.5"`, `"positive"` or `"2.9*"` → **text only**.
3. `flag` is one of `normal`, `high`, `low`, `critical`, `abnormal` (`unknown` / missing → **text only**).
4. The position **agrees with the flag**: `high` → value > high; `low` → value < low; `normal` → low ≤ value ≤ high; `critical` / `abnormal` → outside the band. **On any disagreement → text only.** On the seed data, Potassium 5.1 against 3.5–5.1 flagged High fails this rule.

Drawing (no invented scale):
- The band [low, high] fills the middle half of the track. Only the two printed limits are labelled; there are no axis numbers.
- Outside the band, the marker moves linearly for up to one band-width, then **clamps at the track end with a ◀/▶ "beyond range" arrow**. Distance past the edge is never shown as a measurement.
- Marker colour follows the flag: amber for high/low/abnormal, red for critical, neutral for normal.
- Accessible name uses the API flag: "Creatinine 2.9 mg/dL, flagged High, reference 0.7 to 1.3".

| Seed result | Range | Flag | Bar? |
|---|---|---|---|
| Creatinine 2.9 | 0.7 – 1.3 | High | yes, clamped ▶ |
| CRP 92 | 0 – 5 | High | yes, clamped ▶ |
| HbA1c 8.4 | 4.0 – 5.6 | High | yes, clamped ▶ |
| White cell count 13.8 | 4.0 – 11.0 | High | yes, inside the overflow zone |
| eGFR 22 | > 90 | Low | **no**: one-sided |
| Potassium 5.1 | 3.5 – 5.1 | High | **no**: position contradicts flag |

## History (COULD; real data only)

- Source: `GET /patients/{id}/timeline?types=lab_result&limit=500`, grouped by `payload.name`, ordered by `payload.collected_at`.
- "Previous {value} · {date}" with ▲/▼ and the difference appears only when an **earlier result for the same test name** exists. The arrow is the arithmetic direction of change, not a clinical judgment, and is drawn in neutral colour.
- "History ›" opens a `Drawer` with `TrendChart` + a table **only with ≥ 2 results**.
- Fresh seed and DEMO: one result per test, so nothing renders (no empty chart, no placeholder arrow).

```
┌──────────────── Creatinine · history ───────────── ✕ ┐
│ TrendChart of the real values                        │
│ 21 Oct 07:40   3.4 mg/dL   High   Unreviewed  report │
│ 19 Oct 06:00   2.9 mg/dL   High   Reviewed    record │
└──────────────────────────────────────────────────────┘
```

## Tablet (768–1179px)
KPI 2 × 2. Attention cards 2 across. The rail goes under the results list.

## Phone (< 768px)

```
┌──────────────────────────────┐
│ Lab results                  │
│ [⇪ Upload lab report]        │ full width
├──────────────┬───────────────┤
│▓PENDING {n} ▓│ ABNORMAL {n}  │ compact KPI 2×2
├──────────────┼───────────────┤
│ CRITICAL {n} │ TOTAL {n}     │
├──────────────┴───────────────┤
│ NEEDS YOUR REVIEW {n}        │
│┌────────────────────────────┐│
││▌Creatinine        ▲ HIGH   ││
││▌2.9 mg/dL                  ││
││▌Reference 0.7 – 1.3        ││
││▌┄[▓▓▓]┄┄┄┄▶ (if rules pass)││
││▌[   ✓ Mark reviewed     ]  ││ full-width primary
│└────────────────────────────┘│
│ [All][Abnormal][Unreviewed]  │
│ 🔍 Search tests               │
│ CRP   92 mg/L   ▲High   ✓    │ row cards
│ Reference 0 – 5              │
└──────────────────────────────┘
```

## DEMO mode
- Data: the same 6 fixture results. KPI cards are populated from them (they are real fixture values, not padding).
- Range bars: Creatinine, CRP, HbA1c, White cell count. Text only: eGFR (one-sided), Potassium (flag mismatch).
- No history arrows or drawer (one result per test).
- Mark reviewed, Review all normal and Upload are refused with the existing preview message ("This action is unavailable in the preview environment…"). Nothing changes on screen.

## States
- Loading: skeleton KPI cards and two skeleton attention cards; never "0".
- Error: KPI values "—"; red banner in the workspace with the message.
- No results: empty state with the Upload CTA.
- Filter with no matches: empty state + "Clear filters".
- Mark reviewed: spinner on that card; on success the card leaves the zone and a screen-reader message is announced. Without `review_lab`: disabled with a tooltip, no bulk button, "View only" note.
- Keyboard: KPI cards are buttons (`aria-pressed`); filter tabs use arrow keys; drawer and dialog trap focus and close with Escape.

## Component map

| Zone | Component |
|---|---|
| Header | `PageHeader` (`meta` = last collected) |
| KPI row | `KpiCard` (dk-kpi styles) |
| Attention | `AttentionCard` + `RangeBar` + Mark reviewed |
| Workspace | `Tabs` (segmented), `SearchInput`, `LabRow`, folded `<details>` |
| Rail | `Progress`, method note |
| Bulk | existing `BulkReviewDialog` |
| History | `Drawer` + `TrendChart` |

## Data
- `GET /investigations` → `labs[]` (`name`, `value`, `unit`, `reference_range`, `flag`, `review_status`, `collected_at`, `event_id`), `reviewed_count`.
- History (COULD): timeline endpoint above (supported in DEMO by the existing mock, which filters by `types`).
- Writes unchanged: `POST /labs/{id}/review`, `uploadReport(file, "lab_report")`.
