import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, session } from "../../api";
import { usePatientId } from "../../session";
import type { HospitalDashboard } from "../../types";

/** Ward round, one patient at a time: pick the bed you are at; the recording and tasks go to that patient. */
export function RoundPatientPicker() {
  const queryClient = useQueryClient();
  const current = usePatientId();
  const dashboard = useQuery<HospitalDashboard>({ queryKey: ["hospital-dashboard"], queryFn: () => get("/hospital/dashboard") });
  const rows = (dashboard.data?.patients || [])
    .filter((row) => row.browsable !== false && row.encounter_status === "active")
    .sort((a, b) => `${a.ward || ""}${a.bed || ""}`.localeCompare(`${b.ward || ""}${b.bed || ""}`, undefined, { numeric: true }));

  return (
    <div className="mb-3">
      <label className="field-label" htmlFor="round-patient">Patient on this round</label>
      <select
        id="round-patient"
        className="input"
        value={current || ""}
        onChange={(event) => {
          session.setPatient(event.target.value);
          queryClient.invalidateQueries();
        }}
        disabled={dashboard.isLoading}
      >
        {!rows.some((row) => row.patient_id === current) && current ? <option value={current}>Current patient</option> : null}
        {rows.map((row) => (
          <option key={row.patient_id} value={row.patient_id}>
            {[row.ward, row.bed].filter(Boolean).join(" / ") || "No bed"} · {row.name} ({row.mrn})
          </option>
        ))}
      </select>
      <span className="small muted">Record one round per patient. The work said is split between the junior doctor and the nurse for you to review.</span>
    </div>
  );
}
