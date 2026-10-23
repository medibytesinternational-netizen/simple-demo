// Inline stroke icons (24px grid). Kept local so the app needs no icon package.
const PATHS: Record<string, string> = {
  overview: "M3 3h8v8H3z M13 3h8v5h-8z M13 10h8v11h-8z M3 13h8v8H3z",
  patients: "M9 11a4 4 0 100-8 4 4 0 000 8z M2 21c0-4 3-6 7-6s7 2 7 6 M16 3.5a4 4 0 010 7.5 M18 15c2.5.8 4 2.8 4 6",
  chart: "M6 2h9l5 5v15H6z M14 2v6h6 M9 13h7 M9 17h5",
  admission: "M3 19V6 M3 15h18v4 M21 15v-3a3 3 0 00-3-3h-8v6 M6.5 12.5a1.5 1.5 0 100-.1",
  safety: "M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z M12 8v5 M12 16v.5",
  billing: "M6 2h12v20l-3-2-3 2-3-2-3 2z M9 7h6 M9 11h6 M9 15h4",
  consult: "M6 3v6a5 5 0 0010 0V3 M11 14v2a4 4 0 008 0v-3 M19 11a2 2 0 100 .1",
  round: "M8 3h8v3H8z M6 4.5H4V22h16V4.5h-2 M8 11h8 M8 15h8 M8 19h5",
  progress: "M4 20h4L19 9l-4-4L4 16z M13 7l4 4",
  icu: "M2 12h4l3-7 4 14 3-7h6",
  referral: "M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6",
  discharge: "M10 3H4v18h6 M14 8l4 4-4 4 M18 12H9",
  alert: "M12 3l10 18H2z M12 10v5 M12 18v.4",
  pill: "M10.5 3.5a5 5 0 017 7l-7 7a5 5 0 01-7-7z M7 7l7 7",
  lab: "M9 3h6 M10 3v6L4 20h16L14 9V3",
  scan: "M4 7V4h3 M17 4h3v3 M20 17v3h-3 M7 20H4v-3 M7 12h10",
  request: "M5 3h14v18H5z M9 8h6 M9 12h6 M9 16h3",
  folder: "M3 6h6l2 2h10v12H3z",
  tasks: "M4 6l2 2 3-3 M11 7h9 M4 13l2 2 3-3 M11 14h9 M11 20h9",
  audit: "M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z M9 12l2 2 4-4",
  leakage: "M3 3v18h18 M7 9l4 4 3-3 6 6",
  refresh: "M20 11a8 8 0 10-2.3 5.7 M20 4v7h-7",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14z M21 21l-5-5",
  close: "M6 6l12 12 M18 6L6 18",
  arrow: "M7 17L17 7 M9 7h8v8",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18z M12 7v5l3 2",
  user: "M12 11a4 4 0 100-8 4 4 0 000 8z M4 21c0-4 4-6 8-6s8 2 8 6",
  check: "M5 12l5 5 9-10",
  chevron: "M9 6l6 6-6 6",
  plus: "M12 5v14 M5 12h14",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  filter: "M4 5h16l-6 7v6l-4 2v-8z",
  bed: "M3 19V6 M3 15h18v4 M21 15v-3a3 3 0 00-3-3h-8v6",
  launcher: "M4 4h4v4H4z M10 4h4v4h-4z M16 4h4v4h-4z M4 10h4v4H4z M10 10h4v4h-4z M16 10h4v4h-4z M4 16h4v4H4z M10 16h4v4h-4z M16 16h4v4h-4z",
};

export function Icon({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name] || PATHS.overview} />
    </svg>
  );
}
