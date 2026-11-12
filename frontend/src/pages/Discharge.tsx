import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, openApiWindow, post } from "../api";
import type { Draft, Meta } from "../types";
import { DraftReview } from "../components/DraftReview";
import { ReadinessPanel } from "../features/f09/ReadinessPanel";
import { SignPanel } from "../features/f09/SignPanel";
import type { Readiness } from "../features/f09/types";
import { Banner, Skeleton } from "../components/ui";
import { NextStepCta } from "../components/NextStepCta";

type Mode = "print" | "view" | "clear";
type TabKey = "summary" | "doctor" | "result" | "unit";
const TABS: { key: TabKey; label: string }[] = [
  { key: "summary", label: "Summary Details" },
  { key: "doctor", label: "Dr Details" },
  { key: "result", label: "Result View" },
  { key: "unit", label: "Unit" },
];

/** Fixed category list, as on the hospital's discharge summary screen. */
const CATEGORIES: { key: string; match: string[] }[] = [
  { key: "OTHERCONSULTANTS", match: ["consultant", "referral"] },
  { key: "ALLERGIES", match: ["allerg"] },
  { key: "FINALDIAGNOSIS", match: ["final diagnosis", "admission diagnosis", "diagnosis"] },
  { key: "SECONDARYDIAGNOSIS", match: ["secondary", "comorbid"] },
  { key: "PROCEDURE", match: ["procedure"] },
  { key: "HISTORY", match: ["history", "presenting"] },
  { key: "INVESTIGATIONS", match: ["investigation", "lab"] },
  { key: "COURSEINHOSPITAL", match: ["course"] },
  { key: "CONDITIONATDISCHARGE", match: ["condition"] },
  { key: "DISCHARGEMEDICATION", match: [] },
  { key: "ADVICEONDISCHARGE", match: ["advice", "instruction"] },
  { key: "FOLLOWUP", match: ["follow"] },
];

const fmtDate = (v?: string | null) => (v ? new Date(v).toLocaleDateString("en-GB") : "");
type Section = { heading: string; paragraphs?: { text: string }[] };
type Med = { drug: string; dose?: string; route?: string; frequency?: string };

export function DischargePage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("view");
  const [tab, setTab] = useState<TabKey>("summary");
  const [draftCopy, setDraftCopy] = useState(false);
  const [logo, setLogo] = useState(true);
  const [printLogo, setPrintLogo] = useState(false);

  const meta = useQuery<Meta>({ queryKey: ["meta"], queryFn: () => get<Meta>("/meta") });
  const readiness = useQuery<Readiness>({ queryKey: ["discharge-readiness"], queryFn: () => get("/discharge/readiness") });
  const drafts = useQuery<{ drafts: Draft[] }>({ queryKey: ["drafts", "F9"], queryFn: () => get("/drafts?feature=F9&limit=1") });
  const generate = useMutation({
    mutationFn: () => post<unknown>("/discharge/generate"),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const draft = drafts.data?.drafts?.[0];
  const signed = Boolean(readiness.data?.already_signed);
  const patient = meta.data?.patient;
  const enc = meta.data?.encounter;
  const cleared = mode === "clear";
  const val = (v?: string | number | null) => (cleared || v == null ? "" : String(v));

  const sections: Section[] = draft?.content?.sections ?? [];
  const meds: Med[] = draft?.content?.medications ?? [];
  const used = new Set<Section>();
  const rows = CATEGORIES.map((cat) => {
    if (cat.key === "DISCHARGEMEDICATION") {
      return { cat: cat.key, item: meds.length ? `${meds.length} items` : "", text: meds.map((m) => [m.drug, m.dose, m.route, m.frequency].filter(Boolean).join(" ")).join("; ") };
    }
    if (cat.key === "ALLERGIES" && patient?.allergies?.length) {
      return { cat: cat.key, item: "", text: patient.allergies.join(", ") };
    }
    const sec = sections.find((s) => !used.has(s) && cat.match.some((m) => s.heading.toLowerCase().includes(m)));
    if (sec) used.add(sec);
    return { cat: cat.key, item: sec?.heading ?? "", text: sec?.paragraphs?.map((p) => p.text).join(" ") ?? "" };
  });

  const status = signed ? "DISCHARGED" : readiness.data?.ready ? "READY" : "IN PROGRESS";
  const claim = !draft ? "No Summary" : draft.status === "approved" ? "Approved Summary" : "Draft Summary";

  const onPrint = () => {
    setMode("print");
    if (draft?.status === "approved") openApiWindow(`/discharge/${draft.id}/print`);
  };

  return (
    <div className="page dc-his">
      <section className="dc-form" aria-label="Discharge summary header">
        <div className="dc-form-top">
          <div className="dc-radios" role="radiogroup" aria-label="Mode">
            <label><input type="radio" name="dc-mode" checked={mode === "print"} onChange={onPrint} /> Print</label>
            <label><input type="radio" name="dc-mode" checked={mode === "view"} onChange={() => setMode("view")} /> View</label>
            <label><input type="radio" name="dc-mode" checked={mode === "clear"} onChange={() => setMode("clear")} /> Clear</label>
          </div>
          <h1 className="dc-form-title">Discharge Summary</h1>
          <div className="dc-form-tools">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => generate.mutate()}
              disabled={generate.isPending || !readiness.data?.ready || signed}
              aria-busy={generate.isPending || undefined}
            >
              {generate.isPending ? "Generating..." : draft ? "Regenerate" : "Generate"}
            </button>
            <button type="button" className="dc-mic" aria-label="Dictate" title="Dictate"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg></button>
          </div>
        </div>

        <div className="field-grid-3">
          <Field label="PatientID" value={val(patient?.mrn)} />
          <Field label="IPNO" value={val(enc?.id?.toUpperCase())} />
          <Field label="Gender" value={val(patient?.sex?.[0]?.toUpperCase())} />
          <Field label="Name" value={val(patient?.name?.toUpperCase())} />
          <Field label="Admit DT" value={val(fmtDate(enc?.admitted_at))} />
          <Field label="Ward/Bed" value={val(enc ? `${enc.ward} / ${enc.bed}` : "")} />
          <Field label="DrName" value={val(enc?.attending?.toUpperCase())} />
          <Field label="Disc.DT" value={val(fmtDate(enc?.discharged_at))} />
          <Field label="RegNo" value={val(patient?.mrn)} />
          <Field label="Discharge Status" value={val(status)} tone={signed ? "ok" : undefined} />
          <div className="gf gf-wide">
            <span className="gf-label">Claim Status</span>
            <input className="input dc-claim" readOnly value={val(claim)} />
          </div>
        </div>

        <div className="dc-checks">
          <label><input type="checkbox" checked={draftCopy} onChange={(e) => setDraftCopy(e.target.checked)} /> DRAFT COPY</label>
          <label><input type="checkbox" checked={logo} onChange={(e) => setLogo(e.target.checked)} /> LOGO</label>
          <label><input type="checkbox" checked={printLogo} onChange={(e) => setPrintLogo(e.target.checked)} /> PRINT LOGO</label>
        </div>
      </section>

      {generate.isError ? <Banner tone="danger" role="alert">The discharge summary was not generated: {(generate.error as Error).message}</Banner> : null}

      <div className="tabs" role="tablist" aria-label="Discharge sections">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" className="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      <div className="dc-tabbody" role="tabpanel">
        {tab === "summary" ? (
          drafts.isLoading ? <Skeleton count={6} /> : (
            <table className="table dc-grid">
              <thead><tr><th style={{ width: "22%" }}>category</th><th style={{ width: "14%" }}>Item Details</th><th>Description</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.cat}>
                    <td>{r.cat}</td>
                    <td className="muted">{cleared ? "" : r.item}</td>
                    <td>{cleared || !r.text ? <span className="muted">-</span> : r.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : null}

        {tab === "doctor" ? (
          <div className="dc-pad">
            {readiness.isLoading ? <Skeleton count={5} /> : <ReadinessPanel readiness={readiness.data} />}
            {draft ? <div className="mt-3"><SignPanel draft={draft} readiness={readiness.data} /></div> : null}
            {signed ? <NextStepCta id="discharge" /> : null}
          </div>
        ) : null}

        {tab === "result" ? (
          <div className="dc-pad">
            {draft
              ? <div className="f09-review"><DraftReview draft={draft} /></div>
              : <p className="muted m-0">No discharge summary yet. Use Generate once the record is complete.</p>}
          </div>
        ) : null}

        {tab === "unit" ? (
          <table className="table dc-grid">
            <tbody>
              <tr><td>WARD</td><td>{val(enc?.ward)}</td></tr>
              <tr><td>BED</td><td>{val(enc?.bed)}</td></tr>
              <tr><td>ENCOUNTER TYPE</td><td>{val(enc?.kind?.toUpperCase())}</td></tr>
              <tr><td>ATTENDING</td><td>{val(enc?.attending)}</td></tr>
              <tr><td>ENCOUNTER STATUS</td><td>{val(enc?.status?.toUpperCase())}</td></tr>
            </tbody>
          </table>
        ) : null}
      </div>
    </div>
  );
}

function Field({ label, value, tone }: { label: string; value: string; tone?: "ok" }) {
  return (
    <label className="gf">
      <span className="gf-label">{label}</span>
      <input className={`input ${tone === "ok" ? "dc-ok" : ""}`} readOnly value={value} />
    </label>
  );
}
