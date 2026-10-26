import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { session } from "../api";

/**
 * Opens a patient's chart the way PR #3's OpenRecordButton does: remember the patient (so every
 * request carries X-Patient-Id), drop cached pages, then go to the patient dashboard. Callers only offer it
 * for rows the server marks browsable; every other patient opens the read-only summary instead.
 */
export function useOpenChart() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return (patientId: string) => {
    session.setPatient(patientId);
    queryClient.clear();
    navigate("/patient");
  };
}
