import type { Color } from "../api/types";
import { COLOR_MEANINGS } from "../lib/format";
import { Icon, type IconName } from "./Icon";
import styles from "./StatusPill.module.css";

const ICONS: Record<Color, IconName> = {
  GREEN: "check",
  YELLOW: "warning",
  RED: "octagon",
};

const TONE: Record<Color, string | undefined> = {
  GREEN: styles.green,
  YELLOW: styles.yellow,
  RED: styles.red,
};

interface StatusPillProps {
  color: Color;
  /** Hide the text label (icon + accessible name only) for very dense rows. */
  compact?: boolean;
}

/** GREEN / YELLOW / RED row status, distinguishable by icon and label as well as colour. */
export function StatusPill({ color, compact = false }: StatusPillProps) {
  const meaning = COLOR_MEANINGS[color];
  return (
    <span className={`${styles.pill} ${TONE[color] ?? ""}`} title={meaning} data-color={color}>
      <Icon name={ICONS[color]} size={13} />
      {compact ? <span className="visually-hidden">{color}</span> : <span>{color}</span>}
      <span className="visually-hidden">: {meaning}</span>
    </span>
  );
}
