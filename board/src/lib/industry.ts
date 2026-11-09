// NAICS → words the chrome uses. Exact code first, then the longest prefix (e.g. "611" covers 611110…).
// The code itself is the fallback label, so an unknown industry is never mislabelled.
export interface IndustryWords {
  label: string;      // "Fitness centers"
  site: string;       // one location: "gym"
  sites: string;      // several: "gyms"
  frontline: string;  // the person on the floor whose day record the hero shows: "Trainer"
}

const MAP: Record<string, IndustryWords> = {
  '713940': { label: 'Fitness centers', site: 'gym', sites: 'gyms', frontline: 'Trainer' },
  '621111': { label: 'Physician offices', site: 'practice', sites: 'practices', frontline: 'Physician' },
  '621210': { label: 'Dental offices', site: 'practice', sites: 'practices', frontline: 'Dentist' },
  '722515': { label: 'Coffee & snack bars', site: 'café', sites: 'cafés', frontline: 'Barista' },
  '722511': { label: 'Full-service restaurants', site: 'restaurant', sites: 'restaurants', frontline: 'Server' },
  '722513': { label: 'Limited-service restaurants', site: 'restaurant', sites: 'restaurants', frontline: 'Crew member' },
  '611': { label: 'Education', site: 'campus', sites: 'campuses', frontline: 'Teacher' },
  '541': { label: 'Professional services', site: 'office', sites: 'offices', frontline: 'Consultant' },
  '5415': { label: 'Software & IT services', site: 'office', sites: 'offices', frontline: 'Engineer' },
  '238': { label: 'Specialty trade contractors', site: 'site', sites: 'sites', frontline: 'Crew lead' },
  '445': { label: 'Grocery stores', site: 'store', sites: 'stores', frontline: 'Store associate' },
  '448': { label: 'Clothing stores', site: 'store', sites: 'stores', frontline: 'Store associate' },
  '812': { label: 'Personal care services', site: 'salon', sites: 'salons', frontline: 'Stylist' },
  '531': { label: 'Real estate', site: 'office', sites: 'offices', frontline: 'Agent' },
  '523': { label: 'Financial services', site: 'office', sites: 'offices', frontline: 'Advisor' },
  '621610': { label: 'Home health care', site: 'branch', sites: 'branches', frontline: 'Nurse' },
  '624410': { label: 'Child care', site: 'center', sites: 'centers', frontline: 'Teacher' },
};

const GENERIC: IndustryWords = { label: '', site: 'site', sites: 'sites', frontline: 'Team member' };

/** Industry words for a NAICS code (exact, then longest prefix). `label` falls back to the code itself; `known` says whether the map had it. */
export function industry(naics?: string | null): IndustryWords & { known: boolean } {
  const code = (naics ?? '').trim();
  if (!code) return { ...GENERIC, label: '', known: false };
  if (MAP[code]) return { ...MAP[code], known: true };
  for (let n = code.length - 1; n >= 2; n--) {
    const hit = MAP[code.slice(0, n)];
    if (hit) return { ...hit, known: true };
  }
  return { ...GENERIC, label: `NAICS ${code}`, known: false };
}
export const industryLabel = (naics?: string | null) => industry(naics).label || (naics ? `NAICS ${naics}` : '');

/** Options for the "New company" select — the exact codes the board has words for, sorted by label. */
export const INDUSTRY_OPTIONS: { naics: string; label: string }[] = Object.entries(MAP)
  .map(([naics, w]) => ({ naics, label: w.label }))
  .sort((a, b) => a.label.localeCompare(b.label));

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'];
/** 8 → "eight"; 13 → "13". */
export const numberWord = (n: number) => (Number.isInteger(n) && n >= 0 && n < WORDS.length ? WORDS[n] : String(n));
export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
