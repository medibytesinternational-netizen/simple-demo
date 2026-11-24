/** All clinical wall-clock dates use the hospital timezone; naive API timestamps are IST. */
export const HOSPITAL_TIME_ZONE = "Asia/Kolkata";

export function parseHospitalDateTime(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;

  const input = value.trim();
  if (!input) return null;
  let normalized = input.replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) normalized += "T12:00:00";
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized)) normalized += "+05:30";
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatHospitalDateTime(
  value: string | Date | null | undefined,
  locale = "en-GB",
  options: Intl.DateTimeFormatOptions = {},
): string {
  const parsed = parseHospitalDateTime(value);
  if (!parsed) return "";
  return new Intl.DateTimeFormat(locale, { ...options, timeZone: HOSPITAL_TIME_ZONE }).format(parsed);
}

export function formatHospitalDate(value: string | Date | null | undefined, locale = "en-GB"): string {
  return formatHospitalDateTime(value, locale, { day: "2-digit", month: "short", year: "numeric" });
}

export function formatHospitalTime(value: string | Date | null | undefined, locale = "en-GB"): string {
  return formatHospitalDateTime(value, locale, { hour: "2-digit", minute: "2-digit" });
}

export function hospitalDateKey(value: string | Date | null | undefined): string {
  const parsed = parseHospitalDateTime(value);
  if (!parsed) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: HOSPITAL_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(parsed);
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

export function hospitalDayNumber(value: string | Date | null | undefined): number | null {
  const key = hospitalDateKey(value);
  if (!key) return null;
  const [year, month, day] = key.split("-").map(Number);
  return Math.floor(Date.UTC(year, month - 1, day) / 86_400_000);
}

export function hospitalToday(): string {
  return hospitalDateKey(new Date());
}

export function hospitalDateTimeInput(value = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: HOSPITAL_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}`;
}

export function hospitalAge(dob: string, today = hospitalToday()): number | null {
  const dobMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dob);
  const todayMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today);
  if (!dobMatch || !todayMatch) return null;
  const birthYear = Number(dobMatch[1]);
  const birthMonth = Number(dobMatch[2]);
  const birthDay = Number(dobMatch[3]);
  const currentYear = Number(todayMatch[1]);
  const currentMonth = Number(todayMatch[2]);
  const currentDay = Number(todayMatch[3]);
  return currentYear - birthYear - (currentMonth < birthMonth || (currentMonth === birthMonth && currentDay < birthDay) ? 1 : 0);
}
