import { Link } from "react-router-dom";
import { NEXT_STEP } from "./nextStep";

export function NextStepCta({ id, className = "mt-3" }: { id: string; className?: string }) {
  const step = NEXT_STEP[id];
  if (!step) return null;
  return (
    <div className={className}>
      <Link className="btn btn-primary" to={step.to}>{step.label} →</Link>
    </div>
  );
}
