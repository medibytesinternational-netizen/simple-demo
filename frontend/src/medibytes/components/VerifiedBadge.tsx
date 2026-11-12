import type { FactStatus } from "../api/types";
import { FACT_STATUS_LABELS } from "../lib/format";
import { Icon, type IconName } from "./Icon";
import styles from "./VerifiedBadge.module.css";

const ICONS: Record<FactStatus, IconName> = {
  verified: "check",
  needs_review: "warning",
  rejected: "cross",
};

const TONE: Record<FactStatus, string | undefined> = {
  verified: styles.verified,
  needs_review: styles.review,
  rejected: styles.rejected,
};

interface VerifiedBadgeProps {
  /** Missing status is treated as "needs review": nothing unproven is shown as verified. */
  status: FactStatus | undefined;
}

export function VerifiedBadge({ status }: VerifiedBadgeProps) {
  const s: FactStatus = status ?? "needs_review";
  return (
    <span className={`${styles.badge} ${TONE[s] ?? ""}`} data-status={s}>
      <Icon name={ICONS[s]} size={13} />
      {FACT_STATUS_LABELS[s]}
    </span>
  );
}
