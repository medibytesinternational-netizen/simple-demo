import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { session } from "../../api";

/**
 * Opens this patient's record: remember the patient, drop cached pages, go to the timeline.
 * Only some records are open in this view; a row marked `browsable: false` gets a disabled button
 * with a reason instead of a click that the server would refuse.
 */
export function OpenRecordButton({ patientId, browsable = true }: { patientId: string; browsable?: boolean }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  if (browsable === false) {
    return (
      <button
        className="btn btn-sm"
        disabled
        aria-disabled="true"
        title="This record is not open in this view"
      >
        Open record
      </button>
    );
  }
  return (
    <button
      className="btn btn-sm"
      onClick={() => {
        session.setPatient(patientId);
        queryClient.clear();
        navigate("/patient");
      }}
    >
      Open record
    </button>
  );
}
