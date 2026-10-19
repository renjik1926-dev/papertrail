// "Passed" and "days left" are decided when an item is displayed, from the viewer's local
// date, and never stored (BUILD_PLAN V7).

export function localToday(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function toUtcDay(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) / 86_400_000;
}

export function daysUntil(dueIso: string, todayIso: string): number {
  return Math.round(toUtcDay(dueIso) - toUtcDay(todayIso));
}

export function isPassed(dueIso: string, todayIso: string): boolean {
  return daysUntil(dueIso, todayIso) < 0;
}

export function relativeLabel(dueIso: string, todayIso: string): string {
  const days = daysUntil(dueIso, todayIso);
  if (days < 0) return "This date has passed — check the letter or contact them";
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `In ${days} days`;
}

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}
