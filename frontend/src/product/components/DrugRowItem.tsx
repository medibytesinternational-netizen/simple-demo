import { useId, useState } from "react";
import type { DrugRow } from "../api/types";
import { formatDose } from "../lib/format";
import { DrugProvenance } from "./DrugProvenance";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";
import styles from "./DrugRowItem.module.css";

interface DrugRowItemProps {
  row: DrugRow;
}

export function DrugRowItem({ row }: DrugRowItemProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const dose = formatDose(row.dose, row.unit);
  const regimen = [dose, row.frequency, row.duration].filter(Boolean);

  return (
    <li className={`${styles.row} ${row.negated ? styles.negated : ""}`} data-color={row.color}>
      <button
        type="button"
        className={styles.summary}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <StatusPill color={row.color} />
        <span className={styles.main}>
          <span className={styles.nameLine}>
            <span className={styles.name}>{row.name}</span>
            {row.negated && <span className={`${styles.tag} ${styles.tagNegated}`}>NOT GIVEN</span>}
            {row.allergen && <span className={`${styles.tag} ${styles.tagAllergen}`}>ALLERGEN</span>}
            {row.second_pass && <span className={`${styles.tag} ${styles.tagInfo}`}>second pass</span>}
            {row.context_repair && <span className={`${styles.tag} ${styles.tagInfo}`}>context repair</span>}
          </span>
          <span className={styles.regimen}>
            {regimen.length > 0 ? regimen.join(" · ") : <span className={styles.missing}>No dose dictated</span>}
          </span>
        </span>
        <span className={styles.more}>
          <span className={styles.moreText}>{open ? "Hide" : "Provenance"}</span>
          <Icon name="chevron" size={16} className={styles.chevron} />
        </span>
      </button>
      {open && <DrugProvenance row={row} id={panelId} />}
    </li>
  );
}
