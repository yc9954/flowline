// Fetches /api/... and falls back to the fixture in ../../fixtures when the API is down,
// so the board always renders. Every page shows where its data came from.
import { useEffect, useRef, useState } from 'react';
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

export const BOARD = 'northwind';
export const API = `/api/boards/${BOARD}`;

export type Origin = 'api' | 'fixture';
export interface Loaded<T> { data: T; origin: Origin; fetchedAt: Date; error?: string }

const cache = new Map<string, Promise<Loaded<unknown>>>();

type Valid<T> = (x: unknown) => x is T;

/** QA switch: `?fixtures=1` on any route renders from the fixtures even when the API is up. */
export const forcedFixtures = () => typeof location !== 'undefined' && new URLSearchParams(location.search).has('fixtures');

async function fetchOrFixture<T>(path: string, fixture: () => T, valid?: Valid<T>, signal?: AbortSignal): Promise<Loaded<T>> {
  if (forcedFixtures()) return { data: fixture(), origin: 'fixture', fetchedAt: new Date(), error: 'forced' };
  try {
    const res = await fetch(path, { signal, headers: { accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: unknown = await res.json();
    if (valid && !valid(data)) throw new Error('unexpected shape from the API');
    const hdr = res.headers.get('date');
    return { data: data as T, origin: 'api', fetchedAt: hdr ? new Date(hdr) : new Date() };
  } catch (e) {
    const error = e instanceof Error ? e.message : String(e);
    return { data: fixture(), origin: 'fixture', fetchedAt: new Date(), error };
  }
}

const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
/** The page can only render if these keys hold arrays. */
const hasArrays = <T,>(...keys: string[]): Valid<T> => (x: unknown): x is T => isObj(x) && keys.every((k) => Array.isArray(x[k]));

export function load<T>(path: string, fixture: () => T, valid?: Valid<T>): Promise<Loaded<T>> {
  let p = cache.get(path) as Promise<Loaded<T>> | undefined;
  if (!p) {
    p = fetchOrFixture(path, fixture, valid);
    cache.set(path, p as Promise<Loaded<unknown>>);
    // do not keep failures cached forever: retry on the next mount after 15 s
    p.then((r) => { if (r.origin === 'fixture') setTimeout(() => cache.delete(path), 15000); });
  }
  return p;
}

export function useLoad<T>(path: string, fixture: () => T, valid?: Valid<T>): Loaded<T> | null {
  const [state, setState] = useState<Loaded<T> | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setState(null);
    load(path, fixture, valid).then((r) => { if (alive.current) setState(r); });
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
  return state;
}

// ---- typed loaders -------------------------------------------------------
export const useOntology = () => useLoad<Ontology>(`${API}/ontology`, () => ontologyFx as unknown as Ontology, hasArrays('nodes', 'edges', 'roles'));
export const useFinding = () => useLoad<Finding>(`${API}/finding`, () => findingFx as unknown as Finding, hasArrays('map', 'sent_back', 'repeated'));
export const usePlans = () => useLoad<PlansPage>(`${API}/plans`, () => plansFx as unknown as PlansPage, hasArrays('plans'));
export const useResults = () => useLoad<Results>(`${API}/results`, () => resultsFx as unknown as Results, hasArrays('series', 'kpis', 'who'));
export const useHistory = () => useLoad<History>(`${API}/history`, () => historyFx as unknown as History, hasArrays('loop', 'versions', 'learned'));
export const useModel = () => useLoad<ModelCheck>(`${API}/model`, () => modelFx as unknown as ModelCheck, hasArrays('components', 'sim_checks', 'demand', 'limits'));
export const useOpening = () => useLoad<Opening>(`${API}/opening`, () => openingFx as unknown as Opening, hasArrays('workstreams', 'blockers'));
export const useSurfaces = () => useLoad<Surfaces>(`${API}/surfaces`, () => surfacesFx as unknown as Surfaces, hasArrays('finance_inbox', 'expansion_lead'));

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
  useLoad<Expansion>(`${API}/expansion${industry ? `?industry=${encodeURIComponent(industry)}` : ''}`, () => expansionFixture(industry), hasArrays('zips', 'industries'));

// Records list: accept either a bare array or { records: [...] }.
export const useRecords = () =>
  useLoad<WorkRecord[]>(`${API}/records`, () => recordsFx as unknown as WorkRecord[], (x): x is WorkRecord[] => Array.isArray(x) || (isObj(x) && Array.isArray(x.records)));
export function asRecordList(x: unknown): WorkRecord[] {
  if (Array.isArray(x)) return x as WorkRecord[];
  if (x && typeof x === 'object' && Array.isArray((x as { records?: unknown }).records)) return (x as { records: WorkRecord[] }).records;
  return [];
}

/** Records on the board: the API's record list length, else the ontology's records_used. Used by every page (sidebar). */
export function useRecordCount(): number | null {
  const recs = useRecords();
  const ont = useOntology();
  if (!recs || !ont) return null;
  const n = recs.origin === 'api' ? asRecordList(recs.data).length : 0;
  return n > 0 ? n : ont.data.records_used;
}

// ---- writes ---------------------------------------------------------------
export async function approvePlan(planId: string): Promise<{ ok: boolean; status: number; body?: unknown; error?: string }> {
  try {
    const res = await fetch(`${API}/plans/${encodeURIComponent(planId)}/approve`, { method: 'POST', headers: { accept: 'application/json' } });
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* empty body is fine */ }
    return { ok: res.ok, status: res.status, body };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function withdrawRecord(id: string): Promise<{ ok: boolean; status: number; error?: string }> {
  try {
    const res = await fetch(`${API}/records/${encodeURIComponent(id)}`, { method: 'DELETE' });
    return { ok: res.ok, status: res.status };
  } catch (e) {
    return { ok: false, status: 0, error: e instanceof Error ? e.message : String(e) };
  }
}
