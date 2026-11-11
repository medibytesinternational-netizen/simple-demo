import type { ReactElement, SVGProps } from "react";

export type IconName =
  | "check"
  | "warning"
  | "cross"
  | "circle"
  | "spinner"
  | "upload"
  | "file"
  | "copy"
  | "download"
  | "chevron"
  | "refresh"
  | "ear"
  | "pulse"
  | "octagon";

const PATHS: Record<Exclude<IconName, "spinner">, ReactElement> = {
  check: <path d="M5 12.5l4.2 4.2L19 7" />,
  warning: (
    <>
      <path d="M12 3.5L2.5 20h19L12 3.5z" />
      <path d="M12 10v4.5M12 17.2v.3" />
    </>
  ),
  cross: <path d="M6 6l12 12M18 6L6 18" />,
  circle: <circle cx="12" cy="12" r="7.5" />,
  octagon: (
    <>
      <path d="M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2z" />
      <path d="M12 7.5v5.5M12 16.2v.3" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </>
  ),
  file: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z" />
      <path d="M14 3v5h5M9 13v3M12 11v7M15 14v1" />
    </>
  ),
  copy: (
    <>
      <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
      <path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v12M7 11l5 5 5-5" />
      <path d="M4 20h16" />
    </>
  ),
  chevron: <path d="M9 6l6 6-6 6" />,
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" />
      <path d="M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5L20 16" />
      <path d="M20 20v-4h-4" />
    </>
  ),
  ear: (
    <>
      <path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-5.5 1.6" />
      <path d="M10 9.5a2 2 0 0 1 4 0" />
    </>
  ),
  pulse: <path d="M3 12h4l2-6 4 12 3-9 2 3h3" />,
};

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
}

/** Decorative stroke icon; always paired with visible or screen-reader text. */
export function Icon({ name, size = 16, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {name === "spinner" ? (
        <>
          <circle cx="12" cy="12" r="8" opacity="0.25" />
          <path d="M20 12a8 8 0 0 0-8-8" />
        </>
      ) : (
        PATHS[name]
      )}
    </svg>
  );
}
