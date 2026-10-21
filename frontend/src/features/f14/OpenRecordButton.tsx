import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { session } from "../../api";

/** Opens this patient's record: remember the patient, drop cached pages, go to the timeline. */
export function OpenRecordButton({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return (
    <button
      className="btn btn-sm"
      onClick={() => {
        session.setPatient(patientId);
        queryClient.clear();
        navigate("/timeline");
      }}
    >
      Open record
    </button>
  );
}
