import { useEffect, useRef } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Shared dialog behaviour: Escape closes, Tab stays inside, the first field (or
 * the dialog) takes focus on open and focus returns to the opener on close.
 */
export function useDialog<T extends HTMLElement>(onClose: () => void, options: { initialFocus?: string; lockScroll?: boolean } = {}) {
  const ref = useRef<T | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const root = ref.current;
    if (!root) return;
    const first = (options.initialFocus && root.querySelector<HTMLElement>(options.initialFocus)) || root.querySelector<HTMLElement>(FOCUSABLE);
    (first || root).focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const head = items[0];
      const tail = items[items.length - 1];
      if (e.shiftKey && document.activeElement === head) { e.preventDefault(); tail.focus(); }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus(); }
    };
    root.addEventListener("keydown", onKey);

    const body = document.body;
    const previousOverflow = body.style.overflow;
    if (options.lockScroll) body.style.overflow = "hidden";

    return () => {
      root.removeEventListener("keydown", onKey);
      if (options.lockScroll) body.style.overflow = previousOverflow;
      if (opener && document.contains(opener)) opener.focus();
    };
    // Mount-only: the dialog sets up once per open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return ref;
}
