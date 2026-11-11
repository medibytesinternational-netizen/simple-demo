import { useEffect, useRef, useState } from "react";
import { copyText } from "../lib/browser";
import surface from "../styles/surface.module.css";
import { Icon } from "./Icon";

type CopyState = "idle" | "copied" | "failed";

interface CopyButtonProps {
  /** Produces the text lazily so large JSON is only serialised on click. */
  getText: () => string;
  label?: string;
}

export function CopyButton({ getText, label = "Copy JSON" }: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const onClick = async () => {
    try {
      await copyText(getText());
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  };

  const text = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label;

  return (
    <button type="button" className={surface.button} onClick={() => void onClick()}>
      <Icon name={state === "copied" ? "check" : "copy"} />
      <span aria-live="polite">{text}</span>
    </button>
  );
}
