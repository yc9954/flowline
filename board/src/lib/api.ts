// Fetches /api/boards/{board}/... for the board on the URL. Three outcomes, and the page shows which one it got:
//   data     — the API answered (or ?fixtures=1 forced the demo fixture)
//   empty    — 404 { state: "no_data_yet" }: the board exists but the model has nothing yet → empty state, never fixtures
//   offline  — unreachable / 5xx / wrong shape → "API offline" with a retry, never fixtures
// Fixtures in ../../fixtures are the demo's prototype data and render only with ?fixtures=1.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useBoard } from './board';
import type {
  Expansion, ExpansionFixture, Finding, History, ModelCheck, Ontology, Opening, PlansPage, Results, Surfaces, WorkRecord,
} from './types';

import ontologyFx from '../../../fixtures/ontology.json';
import findingFx from '../../../fixtures/finding.json';
import plansFx from '../../../fixtures/plans.json';
import resultsFx from '../../../fixtures/results.json';
import historyFx from '../../../fixtures/history.json';
import modelFx from '../../../fixtures/model.json';
import expansionFx from '../../../fixtures/expansion.json';
import openingFx from '../../../fixtures/opening.json';
import surfacesFx from '../../../fixtures/surfaces.json';
import recordsFx from '../../../fixtures/records.json';

export type Origin = 'api' | 'fixture';
/** The page has data to render. */
export interface Loaded<T> { kind: 'data'; data: T; origin: Origin; fetchedAt: Date; error?: string }
export interface Empty { kind: 'empty'; state: string; detail?: string }
export interface Offline { kind: 'offline'; error: string; status: number }
export type Fetched<T> = Loaded<T> | Empty | Offline;
/** What a hook returns: `null` while loading, otherwise the outcome plus a retry. */
export type Result<T> = (Fetched<T> & { retry: () => void }) | null;

const cache = new Map<string, Promise<Fetched<unknown>>>();

type Valid<T> = (x: unknown) => x is T;

/** QA switch: `?fixtures=1` on any route renders from the fixtures even when the API is up. */
export const forcedFixtures = () => typeof location !== 'undefined' && new URLSearchParams(location.search).has('fixtures');

const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);

async function fetchOutcome<T>(path: string, fixture: () => T, valid?: Valid<T>, signal?: AbortSignal): Promise<Fetched<T>> {
  if (forcedFixtures()) return { kind: 'data', data: fixture(), origin: 'fixture', fetchedAt: new Date(), error: 'forced' };
  try {
    const res = await fetch(path, { signal, headers: { accept: 'application/json' } });
    if (res.status === 404) {
      let body: unknown = null;
      try { body = await res.json(); } catch { /* no body */ }
      if (isObj(body) && typeof body.state === 'string') return { kind: 'empty', state: body.state, detail: typeof body.detail === 'string' ? body.detail : undefined };
      // a 404 without a state: the board is unknown to the API, or the route is not implemented
      const detail = isObj(body) && typeof body.detail === 'string' ? body.detail : 'HTTP 404';
      if (/no API route/i.test(detail)) return { kind: 'offline', error: `${detail} (not implemented by this API)`, status: 404 };
      return { kind: 'empty', state: 'no_such_board', detail };
    }
    if (!res.ok) return { kind: 'offline', error: `HTTP ${res.status}`, status: res.status };
    const data: unknown = await res.json();
    if (valid && !valid(data)) return { kind: 'offline', error: 'unexpected shape from the API', status: res.status };
    const hdr = res.headers.get('date');
    return { kind: 'data', data: data as T, origin: 'api', fetchedAt: hdr ? new Date(hdr) : new Date() };
  } catch (e) {
    return { kind: 'offline', error: e instanceof Error ? e.message : String(e), status: 0 };
  }
}

/** The page can only render if these keys hold arrays. */
const hasArrays = <T,>(...keys: string[]): Valid<T> => (x: unknown): x is T => isObj(x) && keys.every((k) => Array.isArray(x[k]));

export function load<T>(path: string, fixture: () => T, valid?: Valid<T>, force = false): Promise<Fetched<T>> {
  let p = force ? undefined : (cache.get(path) as Promise<Fetched<T>> | undefined);
  if (!p) {
    p = fetchOutcome(path, fixture, valid);
    cache.set(path, p as Promise<Fetched<unknown>>);
    // offline answers are retried on the next mount after 15 s; empty ones after 60 s (records arrive in the evening)
    p.then((r) => {
      if (r.kind === 'offline') setTimeout(() => cache.delete(path), 15000);
      else if (r.kind === 'empty') setTimeout(() => cache.delete(path), 60000);
    });
  }
  return p;
}

export function useLoad<T>(path: string, fixture: () => T, valid?: Valid<T>): Result<T> {
  const [state, setState] = useState<Fetched<T> | null>(null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setState(null);
    load(path, fixture, valid, tick > 0).then((r) => { if (alive.current) setState(r); });
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick]);
  const retry = useCallback(() => { cache.delete(path); setTick((t) => t + 1); }, [path]);
  return state ? { ...state, retry } : null;
}

// ---- typed loaders (all relative to the board on the URL) --------------------------------------------------
export const useOntology = () => useLoad<Ontology>(`${useBoard().api}/ontology`, () => ontologyFx as unknown as Ontology, hasArrays('nodes', 'edges', 'roles'));
export const useFinding = () => useLoad<Finding>(`${useBoard().api}/finding`, () => findingFx as unknown as Finding, hasArrays('map', 'sent_back', 'repeated'));
export const usePlans = () => useLoad<PlansPage>(`${useBoard().api}/plans`, () => plansFx as unknown as PlansPage, hasArrays('plans'));
export const useResults = () => useLoad<Results>(`${useBoard().api}/results`, () => resultsFx as unknown as Results, hasArrays('series', 'kpis', 'who'));
export const useHistory = () => useLoad<History>(`${useBoard().api}/history`, () => historyFx as unknown as History, hasArrays('loop', 'versions', 'learned'));
export const useModel = () => useLoad<ModelCheck>(`${useBoard().api}/model`, () => modelFx as unknown as ModelCheck, hasArrays('components', 'sim_checks', 'demand', 'limits'));
export const useOpening = () => useLoad<Opening>(`${useBoard().api}/opening`, () => openingFx as unknown as Opening, hasArrays('workstreams', 'blockers'));
export const useSurfaces = () => useLoad<Surfaces>(`${useBoard().api}/surfaces`, () => surfacesFx as unknown as Surfaces, hasArrays('finance_inbox', 'expansion_lead'));

// The fixture holds every industry; the API returns one flat Expansion per ?industry=. Merge here.
export function expansionFixture(industry?: string): Expansion {
  const fx = expansionFx as unknown as ExpansionFixture;
  const key = industry && fx.by_industry[industry] ? industry : fx.default;
  const part = fx.by_industry[key];
  return {
    source: fx.source, board_id: fx.board_id, city: fx.city, industries: fx.industries,
    records: fx.records, branches: fx.branches, ...part, industry: key,
  };
}
export const useExpansion = (industry?: string) =>
  useLoad<Expansion>(`${useBoard().api}/expansion${industry ? `?industry=${encodeURIComponent(industry)}` : ''}`, () => expansionFixture(industry), hasArrays('zips', 'industries'));

// Records list: accept either a bare array or { records: [...] }.
export const useRecords = () =>
  useLoad<WorkRecord[]>(`${useBoard().api}/records`, () => recordsFx as unknown as WorkRecord[], (x): x is WorkRecord[] => Array.isArray(x) || (isObj(x) && Array.isArray(x.records)));
export function asRecordList(x: unknown): WorkRecord[] {
  if (Array.isArray(x)) return x as WorkRecord[];
  if (x && typeof x === 'object' && Array.isArray((x as { records?: unknown }).records)) return (x as { records: WorkRecord[] }).records;
  return [];
}

/** Records on the board: the API's record list length, else the ontology's records_used, else `fallback` (the board record's count). */
export function useRecordCount(fallback?: number | null): number | null {
  const recs = useRecords();
  const ont = useOntology();
  if (!recs || !ont) return fallback ?? null;
  const n = recs.kind === 'data' && recs.origin === 'api' ? asRecordList(recs.data).length : 0;
  if (n > 0) return n;
  if (ont.kind === 'data') return ont.data.records_used;
  if (recs.kind === 'data') return asRecordList(recs.data).length;
  return fallback ?? null;
}

// ---- writes ---------------------------------------------------------------------------------------------------
export async function approvePlan(api: string, planId: string): Promise<{ ok: boolean; status: number; body?: unknown; error?: string }> {
  try {
    const res = await fetch(`${api}/plans/${encodeURIComponent(planId)}/approve`, { method: 'POST', headers: { accept: 'application/json' } });
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* empty body is fine */ }
    return { ok: res.ok, status: res.status, body };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function withdrawRecord(api: string, id: string): Promise<{ ok: boolean; status: number; error?: string }> {
  try {
    const res = await fetch(`${api}/records/${encodeURIComponent(id)}`, { method: 'DELETE' });
    return { ok: res.ok, status: res.status };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}

// ---- people (onboarding) --------------------------------------------------------------------------------------
export type InviteStatus = 'not_invited' | 'invited' | 'joined';
export interface Person {
  id: string; name: string; role: string; email?: string | null; target: string /* "mac" | "desk1"… */;
  skill_id?: string | null; pre_approved: boolean;
  invite_status: InviteStatus; invite_code?: string | null; joined_at?: string | null; invited_at?: string | null;
}
export function asPeople(x: unknown): Person[] {
  const arr = Array.isArray(x) ? x : isObj(x) && Array.isArray(x.people) ? x.people : [];
  return arr.filter(isObj).map((p) => ({
    id: String(p.id ?? ''), name: String(p.name ?? ''), role: String(p.role ?? ''), email: typeof p.email === 'string' ? p.email : null,
    target: String(p.target ?? 'mac'), skill_id: typeof p.skill_id === 'string' ? p.skill_id : null, pre_approved: p.pre_approved === true,
    invite_status: (p.invite_status === 'invited' || p.invite_status === 'joined' ? p.invite_status : p.joined_at ? 'joined' : p.invite_code || p.invited_at ? 'invited' : 'not_invited') as InviteStatus,
    invite_code: typeof p.invite_code === 'string' ? p.invite_code : null,
    joined_at: typeof p.joined_at === 'string' ? p.joined_at : null, invited_at: typeof p.invited_at === 'string' ? p.invited_at : null,
  })).filter((p) => p.id);
}
export const usePeople = () => useLoad<unknown>(`${useBoard().api}/people`, () => [], (x): x is unknown => Array.isArray(x) || (isObj(x) && Array.isArray(x.people)));

export interface NewPerson { name: string; role: string; email: string; target: string; skill_id: string; pre_approved: boolean }
type WriteResult<T> = { ok: true; body: T } | { ok: false; error: string; status: number };
async function post<T>(url: string, body?: unknown): Promise<WriteResult<T>> {
  try {
    const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    let out: unknown = null;
    try { out = await res.json(); } catch { /* empty */ }
    if (!res.ok) return { ok: false, status: res.status, error: isObj(out) && typeof out.detail === 'string' ? out.detail : `HTTP ${res.status}` };
    return { ok: true, body: out as T };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}
export const addPerson = (api: string, p: NewPerson) => post<unknown>(`${api}/people`, p);
export const issueInvite = (api: string, pid: string) => post<{ invite_code?: string; api_url?: string }>(`${api}/people/${encodeURIComponent(pid)}/invite`);
/** Drop the cached people list after a write so the next load refetches. */
export const forgetPeople = (api: string) => cache.delete(`${api}/people`);
