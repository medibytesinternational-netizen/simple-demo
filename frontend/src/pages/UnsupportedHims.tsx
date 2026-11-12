import { Link } from "react-router-dom";
import styles from "./UnsupportedHims.module.css";

const AREAS = [
  {
    title: "Patient workspace",
    items: ["Patient registration and directory", "Patient-scoped timeline and chart", "Consent capture and identity management"],
  },
  {
    title: "Clinical workflows",
    items: ["Consultation, admission, round and progress-note drafting", "Clinical approvals, signing and encounter locking", "ICU charting and nursing handover"],
  },
  {
    title: "Safety and results",
    items: ["Clinical alert evaluation and acknowledgement", "Medication reconciliation and allergy verification", "Lab review and result confirmation"],
  },
  {
    title: "Documents and coordination",
    items: ["OCR intake, field confirmation and chart commit", "Investigation and referral request lifecycles", "Records follow-up and pre-authorisation"],
  },
  {
    title: "Hospital operations",
    items: ["HIMS discharge readiness and signing", "Claim and TPA preparation, billing reconciliation and revenue leakage", "Task assignment, escalation, dashboards and audit workflows"],
  },
];

export function UnsupportedHimsPage() {
  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Capability status</p>
        <h1>HIMS workflows need a separate implementation</h1>
        <p>
          This workspace runs the MediBytes audio processing pipeline. It does not read or write patient charts, approve
          clinical actions, or expose the former HIMS workflow endpoints. These controls are intentionally unavailable
          until a compatible HIMS service is implemented.
        </p>
      </header>

      <div className={styles.grid}>
        {AREAS.map((area) => (
          <section className={styles.card} key={area.title}>
            <h2>{area.title}</h2>
            <ul>{area.items.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        ))}
      </div>

      <aside className={styles.note}>
        <h2>What is available</h2>
        <p>
          The processing screen accepts audio and returns job progress, transcripts, extracted entities, verification
          results, a six-section discharge-note draft and downloadable files. Product also includes an optional,
          key-protected transcription delivery API for a configured HIMS callback; it does not implement the workflows
          listed above.
        </p>
        <Link to="/pipeline">Open the dictation pipeline</Link>
      </aside>
    </section>
  );
}
