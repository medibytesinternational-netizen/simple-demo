// Who can see what. One place to edit role access: the sidebar, the Ctrl+K search and the
// page guard in the shell all read from here. The server still enforces every action.
import { session } from "../api";

export type AppRole = "admin" | "senior" | "junior" | "nurse";

/** Staff who can sign in. `role` is the server's role id; `app` is the role the UI uses. */
export const STAFF = [
  { id: "u_meera", name: "Dr. Meera Shah", role: "doctor", app: "admin" as AppRole, label: "Admin" },
  { id: "u_arjun", name: "Dr. Arjun Rao", role: "senior_doctor", app: "senior" as AppRole, label: "Senior doctor" },
  { id: "u_kiran", name: "Dr. Kiran Patel", role: "junior_doctor", app: "junior" as AppRole, label: "Junior doctor" },
  { id: "u_anita", name: "Nurse Anita Rao", role: "nurse", app: "nurse" as AppRole, label: "Nurse" },
];
export const DEFAULT_STAFF_ID = "u_meera";

type RoleConfig = {
  label: string;
  /** Page the role lands on after sign-in or role switch. */
  home: string;
  /** Nav item ids (see modules.ts) this role sees, or "all". */
  pages: "all" | string[];
};

// PLACEHOLDER access for Senior, Junior and Nurse: to be replaced with the hospital's
// confirmed list. Admin sees everything.
export const ROLES: Record<AppRole, RoleConfig> = {
  admin: { label: "Admin", home: "/dashboard", pages: "all" },
  senior: {
    label: "Senior doctor",
    home: "/tasks",
    pages: [
      "dashboard", "new-patient", "patients", "overview-patient", "timeline", "patient-progress",
      "consult", "admission", "round", "progress", "icu", "referral", "discharge",
      "alerts", "meds", "labs", "inbound", "requisition", "followup", "tasks",
    ],
  },
  junior: {
    label: "Junior doctor",
    home: "/tasks",
    pages: [
      "new-patient", "patients", "overview-patient", "timeline", "patient-progress",
      "consult", "admission", "round", "progress", "icu", "referral",
      "alerts", "meds", "labs", "inbound", "requisition", "tasks",
    ],
  },
  nurse: {
    label: "Nurse",
    home: "/tasks",
    pages: ["patients", "overview-patient", "timeline", "round", "icu", "alerts", "meds", "labs", "tasks"],
  },
};

export function staffById(id: string | null | undefined) {
  return STAFF.find((s) => s.id === id) || STAFF.find((s) => s.id === DEFAULT_STAFF_ID)!;
}

/** The signed-in role, read synchronously from the session so the nav never flashes. */
export function currentRole(): AppRole {
  return staffById(session.user()).app;
}

export function canSee(role: AppRole, itemId: string): boolean {
  const pages = ROLES[role].pages;
  return pages === "all" || pages.includes(itemId);
}
