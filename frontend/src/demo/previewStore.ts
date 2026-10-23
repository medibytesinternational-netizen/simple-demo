// In-memory state for UI-preview interactions (registration, documents, admissions).
// Deliberately not persisted: everything is cleared when the tab is refreshed or closed.
import { useSyncExternalStore } from "react";

export type PreviewPatient = {
  id: string;
  mrn: string;
  name: string;
  sex: string;
  dob: string;
  phone: string;
  address: string;
  emergencyName: string;
  emergencyPhone: string;
  bloodGroup: string;
  allergies: string[];
  problems: string[];
  createdAt: string;
};

export type PreviewEncounter = {
  id: string;
  patientId: string;
  kind: string;
  ward: string;
  bed: string;
  attending: string;
  admittedAt: string;
  reason: string;
  notes: string;
  allergyCheckedBy: string;
  createdAt: string;
};

export type PreviewDocument = {
  id: string;
  patientId: string;
  filename: string;
  mime: string;
  size: number;
  docType: string;
  url: string;
  uploadedAt: string;
  archived?: { reason: string; at: string };
};

type State = {
  patients: PreviewPatient[];
  edits: Record<string, Partial<PreviewPatient>>;
  encounters: PreviewEncounter[];
  documents: PreviewDocument[];
};

let state: State = { patients: [], edits: {}, encounters: [], documents: [] };
const listeners = new Set<() => void>();
let counter = 0;

function set(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}

const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}${(counter++).toString(36)}`;

export const previewStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  get: () => state,
  addPatient(input: Omit<PreviewPatient, "id" | "mrn" | "createdAt">) {
    const patient: PreviewPatient = {
      ...input,
      id: nextId("preview"),
      mrn: `PV-${String(state.patients.length + 1).padStart(4, "0")}`,
      createdAt: new Date().toISOString(),
    };
    set({ patients: [...state.patients, patient] });
    return patient;
  },
  updatePatient(id: string, changes: Partial<PreviewPatient>) {
    set({ patients: state.patients.map((p) => (p.id === id ? { ...p, ...changes } : p)) });
  },
  addEncounter(input: Omit<PreviewEncounter, "id" | "createdAt">) {
    const encounter: PreviewEncounter = { ...input, id: nextId("enc_preview"), createdAt: new Date().toISOString() };
    set({ encounters: [...state.encounters, encounter] });
    return encounter;
  },
  addDocument(patientId: string, file: File, docType: string) {
    const doc: PreviewDocument = {
      id: nextId("doc_preview"),
      patientId,
      filename: file.name,
      mime: file.type || "application/octet-stream",
      size: file.size,
      docType,
      url: URL.createObjectURL(file),
      uploadedAt: new Date().toISOString(),
    };
    set({ documents: [...state.documents, doc] });
    return doc;
  },
  archiveDocument(id: string, reason: string) {
    set({ documents: state.documents.map((d) => (d.id === id ? { ...d, archived: { reason, at: new Date().toISOString() } } : d)) });
  },
};

export function usePreviewState() {
  return useSyncExternalStore(previewStore.subscribe, previewStore.get, previewStore.get);
}
