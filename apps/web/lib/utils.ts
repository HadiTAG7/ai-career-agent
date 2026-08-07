import clsx, { type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatDemoDate(value: string, locale: "ar" | "en") {
  const candidate = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value;
  const date = new Date(candidate);
  if (Number.isNaN(date.getTime())) return locale === "ar" ? "تاريخ غير متاح" : "Date unavailable";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar-SA" : "en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function normalizeApiDate(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "";
  const trimmed = value.trim();
  const calendarDate = trimmed.match(/^(\d{4}-\d{2}-\d{2})/)?.[1];
  if (calendarDate) {
    const parsedCalendarDate = new Date(`${calendarDate}T12:00:00Z`);
    if (!Number.isNaN(parsedCalendarDate.getTime())) return calendarDate;
  }
  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(0, 10);
}
