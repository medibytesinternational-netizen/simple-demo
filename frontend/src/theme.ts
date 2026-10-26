import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "mb-theme";
const THEME_COLOR: Record<Theme, string> = { light: "#1b2a4a", dark: "#0f1626" };

// Storage can be unavailable (private windows, blocked site data); the theme then follows the OS.
function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function readTheme(): Theme {
  return stored() ?? systemTheme();
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
}

/** Current theme plus a toggle. Follows OS changes until the user picks one. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => { if (!stored()) setTheme(systemTheme()); };
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch { /* the choice lasts for this page only */ }
      return next;
    });
  }, []);

  return { theme, toggle };
}
