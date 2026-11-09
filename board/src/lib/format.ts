import type { Role } from './types';

const DAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYLONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONLONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

export const pad2 = (n: number) => String(n).padStart(2, '0');

/**
 * Parse an ISO date (YYYY-MM-DD) or timestamp into a Date whose *UTC* fields equal the wall-clock
 * time written in the string (its own offset is honoured, the machine's timezone is ignored).
 * Format with getUTC* only. A Date object passed through is treated as "now, local".
 */
export function parseDate(s: string | Date): Date {
  if (s instanceof Date) return new Date(s.getTime() - s.getTimezoneOffset() * 60000);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T00:00:00Z`);
  const m = s.match(/(Z|[+-]\d{2}:?\d{2})$/);
  const t = Date.parse(s);
  if (isNaN(t)) return new Date(NaN);
  if (!m) return new Date(t - new Date(t).getTimezoneOffset() * 60000); // no offset: assume local wall clock
  if (m[1] === 'Z') return new Date(t);
  const sign = m[1][0] === '-' ? -1 : 1;
  const hh = Number(m[1].slice(1, 3)), mm = Number(m[1].slice(-2));
  return new Date(t + sign * (hh * 60 + mm) * 60000);
}
const ok = (d: Date) => !isNaN(d.getTime());

/** "Wed 18:24" — the recomputed stamp. */
export function dayTime(iso: string | Date): string {
  const d = parseDate(iso);
  return ok(d) ? `${DAY[d.getUTCDay()]} ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}` : String(iso);
}
export function hhmm(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}` : iso;
}
export function hhmmss(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}` : iso;
}
/** "12 Jan" */
export function dayMon(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${d.getUTCDate()} ${MON[d.getUTCMonth()]}` : iso;
}
/** "Wed 11 Dec" */
export function wdDayMon(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${DAY[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}` : iso;
}
/** "Wednesday 6 November" */
export function longDate(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${DAYLONG[d.getUTCDay()]} ${d.getUTCDate()} ${MONLONG[d.getUTCMonth()]}` : iso;
}
/** "6 Nov 2026" */
export function dayMonYear(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? `${d.getUTCDate()} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}` : iso;
}
export function weekday(iso: string): string {
  const d = parseDate(iso);
  return ok(d) ? DAY[d.getUTCDay()] : iso;
}
/** ISO-8601 week number of a wall-clock Date (UTC fields). */
export function isoWeek(d: Date): number {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNum = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}
export function daysBetween(a: string, b: string): number {
  return Math.round((parseDate(b).getTime() - parseDate(a).getTime()) / 86400000);
}

/** Evenly spaced "nice" ticks from 0 (or lo) to >= max with about `target` steps (steps 1,2,5 × 10^n). */
export function niceStep(span: number, target = 6): number {
  const raw = span / Math.max(1, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw) return m * mag;
  return 10 * mag;
}
export function niceTicks(lo: number, hi: number, target = 6): number[] {
  const step = niceStep(hi - lo, target);
  const start = Math.floor(lo / step) * step;
  const out: number[] = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1000) / 1000);
  return out;
}

export const h1 = (h: number) => `${h.toFixed(1)} h`;
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const signedPct = (x: number) => (Math.abs(x) < 0.005 ? '—' : `${x < 0 ? '−' : '+'}${Math.abs(Math.round(x * 100))}%`);
export const signed1 = (x: number) => `${x < 0 ? '−' : '+'}${Math.abs(x).toFixed(1)}`;
export const signedInt = (x: number) => `${x < 0 ? '−' : '+'}${Math.abs(Math.round(x))}`;
export const int = (n: number) => n.toLocaleString('en-US');

/** 18 → "18 m", 300 → "5.0 h", 564 → "9.4 h" */
export function minutes(min: number): string {
  if (min < 60) return `${Math.round(min)} m`;
  return `${(min / 60).toFixed(1)} h`;
}
/** 246 → "4 h 06 m" */
export function hoursMinutes(min: number): string {
  const h = Math.floor(min / 60), m = Math.round(min % 60);
  if (h === 0) return `${m} m`;
  return `${h} h ${pad2(m)} m`;
}

export const ROLE_LABEL: Record<string, string> = {
  BranchMgr: 'Branch manager', PM: 'PM', CEO: 'CEO',
};
export const roleLabel = (r: Role | string) => ROLE_LABEL[r] ?? r;
export const roleShort = (r: Role | string) => (r === 'BranchMgr' ? 'Branch mgr' : roleLabel(r));

// Lane / owner colours. Styling, not data.
export const ROLE_COLOR: Record<string, string> = {
  Client: '#F99C00', Sales: '#3B73FF', PM: '#88ACFA', Design: '#5e6875', Finance: '#104e64', Director: '#171717',
  Legal: '#9aa1a6', Trainer: '#0F766E', BranchMgr: '#30373f', Ops: '#B8BEC2', CEO: '#000',
};
export const roleColor = (r: Role | string) => ROLE_COLOR[r] ?? '#9aa1a6';

export function sourceLabel(source?: string): 'SIMULATED' | 'PROTOTYPE' | null {
  if (source === 'simulated') return 'SIMULATED';
  if (source === 'prototype') return 'PROTOTYPE';
  return null;
}
