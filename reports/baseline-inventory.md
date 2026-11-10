# Baseline inventory

Source: the `simple-demo-main.zip` snapshot supplied by the user. The archive contains no Git metadata.

## Existing architecture

- Frontend: React 18, TypeScript, Vite, React Router, and TanStack Query.
- Backend: FastAPI, SQLAlchemy, and SQLite, with the F1-F16 module registry.
- Existing routes: `/dashboard`, `/patients`, `/patient`, `/timeline`, `/progress`, `/notes`, `/safety`, `/tasks`, `/documents`, `/discharge`, `/revenue`, and `/audit`.
- `modules.ts` is the grouped navigation registry. `Shell.tsx` renders `MenuBar`; `Dock.tsx` and `Launchpad.tsx` are present in source but not mounted by the existing shell.
- Patient selection and query parameters carry patient context through existing routes and API calls.

## Baseline navigation and workflow

- The Dashboard shows 7 top navigation controls: 2 workspace tabs, 2 quick links, 2 section tabs, and 1 module link.
- Before: on patient routes, the direct Discharge Summary and Emergency Alerts links duplicate the Discharge and Clinical alerts destinations in the section menu (2 duplicate destinations).
- Clinical draft review, OCR confirmation, alert dismissal with a reason, medicine reconciliation, task transitions, discharge signing, claim review, and audit events use existing pages and APIs.
- Preview mode reads synthetic fixtures and refuses writes. The review/signature gates remain human controlled.
- The original Dashboard has an operational summary and a needs-attention table; the CTA was absent in the supplied ZIP.

## Baseline evidence and final scope

- Original Dashboard screenshot: `reports/screenshots/before-dashboard.png` (1440 x 1000).
- After screenshot: `reports/screenshots/after-dashboard.png` (1440 x 1000), showing the contextual Dashboard CTA and the reduced row-action buttons.
- The site theme remains unchanged. Repeated Dashboard row buttons were removed from the Needs Attention and Patients tables; patient names now open the matching chart or summary. The redundant Patient list header button was removed because the PATIENT workspace tab already opens that route.
- On open patient pages, the two duplicate quick links are hidden because the Clinical care and Safety & results section menus provide those destinations. All routes remain accessible, and the Dashboard navigation retains its 7 controls.
- The CTA reads the existing needs-attention data and opens the matching safety, task, document, draft, discharge, or billing page. It preserves the selected patient when a chart is available and falls back to that patient's summary otherwise.
- A cold Dashboard preview has 17 logical fixture reads from existing query definitions and 0 browser HTTP requests to `/api/*` in the cached preview.
- Frontend build passed after the CTA change. Backend compile, the F1-F16 contract check, all backend tests, and the Playwright route, CTA, and responsive-layout suite passed.
- Playwright was not present in the original project; it is added as a development-only dependency with 3 E2E checks.

## Fixture limits recorded

- In preview fixtures, `/hospital/dashboard` reports 8 open alerts while `/alerts` reports 0 open alerts. The values are not reconciled by this work.
- The preview Dashboard fixture omits `medicine_discrepancies`, and the original UI renders that value blank.
- The E2E suite checks route loading, menu structure, duplicate destinations, CTA visibility and navigation, and responsive width. It does not exercise write operations or live API state.
