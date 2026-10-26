import { useQueries, useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { HospitalDashboard } from "../types";
import { DEMO_MODE } from "../demo/config";
import { usePreviewState } from "../demo/previewStore";
import type { PreviewEncounter, PreviewPatient } from "../demo/previewStore";
import { bedKey } from "./wards";

export type DirectoryRow = {
  id: string;
  name: string;
  mrn: string;
  age: number | null;
  sex: string;
  dob?: string;
  allergies: string[];
  /** False when the allergy record could not be read (the server refuses records outside this view). */
  allergiesKnown: boolean;
  problems: string[];
  kind: string | null;
  ward: string | null;
  bed: string | null;
  status: "active" | "discharged" | "not admitted";
  openAlerts: number;
  criticalAlerts: number;
  overdueTasks: number;
  flags: string[];
  source: "seed" | "preview";
  chartAvailable: boolean;
  previewEncounter?: PreviewEncounter;
  previewPatient?: PreviewPatient;
};

export const CHART_PATIENT_ID = "pat_ravi";

export function ageFrom(dob: string, now = new Date()) {
  const birth = new Date(dob);
  let age = now.getFullYear() - birth.getFullYear();
  const m = now.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < birth.getDate())) age -= 1;
  return age;
}

export function usePatientDirectory() {
  const preview = usePreviewState();
  const dashboard = useQuery<HospitalDashboard>({ queryKey: ["hospital-dashboard"], queryFn: () => get("/hospital/dashboard") });
  const seedRows = dashboard.data?.patients || [];
  const details = useQueries({
    queries: seedRows.map((row) => ({
      queryKey: ["patient-detail", row.patient_id],
      queryFn: () => get<{ patient: { allergies: string[]; problems: string[] } }>(`/patients/${row.patient_id}`),
      staleTime: 60_000,
      // The server refuses clinical detail for patients outside this view.
      enabled: row.browsable ?? row.patient_id === CHART_PATIENT_ID,
    })),
  });

  const encounterFor = (id: string) => (DEMO_MODE ? preview.encounters.find((e) => e.patientId === id) : undefined);

  const rows: DirectoryRow[] = seedRows.map((row, index) => {
    const detail = details[index]?.data?.patient;
    const enc = encounterFor(row.patient_id);
    return {
      id: row.patient_id,
      name: row.name,
      mrn: row.mrn,
      age: row.age,
      sex: row.sex,
      allergies: detail?.allergies || [],
      allergiesKnown: !!detail,
      problems: detail?.problems || [],
      kind: enc ? enc.kind : row.kind || null,
      ward: enc ? enc.ward : row.ward || null,
      bed: enc ? enc.bed : row.bed || null,
      status: enc ? "active" : row.encounter_status === "discharged" ? "discharged" : row.encounter_status === "active" ? "active" : "not admitted",
      openAlerts: row.open_alerts,
      criticalAlerts: row.critical_alerts,
      overdueTasks: row.overdue_tasks,
      flags: row.flags,
      source: "seed",
      chartAvailable: row.browsable ?? row.patient_id === CHART_PATIENT_ID,
      previewEncounter: enc,
    };
  });

  if (DEMO_MODE) {
    for (const patient of preview.patients) {
      const enc = encounterFor(patient.id);
      rows.push({
        id: patient.id,
        name: patient.name,
        mrn: patient.mrn,
        age: ageFrom(patient.dob),
        sex: patient.sex,
        dob: patient.dob,
        allergies: patient.allergies,
        allergiesKnown: true,
        problems: patient.problems,
        kind: enc?.kind || null,
        ward: enc?.ward || null,
        bed: enc?.bed || null,
        status: enc ? "active" : "not admitted",
        openAlerts: 0,
        criticalAlerts: 0,
        overdueTasks: 0,
        flags: [],
        source: "preview",
        chartAvailable: false,
        previewEncounter: enc,
        previewPatient: patient,
      });
    }
  }

  const occupied = new Map<string, string>();
  for (const row of rows) {
    if (row.status === "active" && row.ward && row.bed) occupied.set(bedKey(row.ward, row.bed), row.name);
  }

  return {
    rows,
    occupied,
    isLoading: dashboard.isLoading,
    error: dashboard.error as Error | null,
    refetch: dashboard.refetch,
  };
}
