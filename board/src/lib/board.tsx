// Which board the URL is on (/b/:boardId/...), the API prefix for it, and the board record from GET /api/boards/{id}.
// Nothing here is a constant: the id comes from the route, the name and counts from the API.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { industryLabel } from './industry';

export interface BoardInfo {
  id: string;
  name: string;
  industry?: string | null;      // NAICS code
  people: number;                // people invited / on the board
  records: number;               // approved records so far
  has_data: boolean;             // the model has produced the §3–§11 files
  mail_domain?: string | null;
  timezone?: string | null;
  city?: string | null;
  api_url?: string | null;       // the address people enter in the Mac app; defaults to this origin
  next_fit_at?: string | null;   // ISO; when the first (next) fit will run, if the API knows
  min_records?: number | null;   // records needed before the first fit
}

export type BoardState =
  | { kind: 'data'; board: BoardInfo }
  | { kind: 'missing' }                      // GET /api/boards/{id} → 404: no board with that id
  | { kind: 'offline'; error: string };      // unreachable, 5xx, or the endpoint does not exist yet

export const boardApi = (id: string) => `/api/boards/${encodeURIComponent(id)}`;

const Ctx = createContext<string | null>(null);

export function BoardProvider({ id, children }: { id: string; children: ReactNode }) {
  return <Ctx.Provider value={id}>{children}</Ctx.Provider>;
}

/** The board on the URL: its id, its API prefix and a `path()` that makes board-relative links absolute. */
export function useBoard(): { id: string; api: string; base: string; path: (p: string) => string } {
  const id = useContext(Ctx);
  if (id == null) throw new Error('useBoard() outside a /b/:boardId route');
  const base = `/b/${encodeURIComponent(id)}`;
  return { id, api: boardApi(id), base, path: (p: string) => (p.startsWith('/b/') ? p : `${base}${p}`) };
}

// ---- board record -------------------------------------------------------------------------------------------
const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);

/** Accepts the contract shape and tolerates missing counts. */
export function asBoardInfo(x: unknown, id: string): BoardInfo | null {
  if (!isObj(x)) return null;
  const name = typeof x.name === 'string' && x.name.trim() ? x.name : id;
  const n = (v: unknown) => (typeof v === 'number' && isFinite(v) ? v : 0);
  return {
    id: typeof x.id === 'string' ? x.id : typeof x.board_id === 'string' ? x.board_id : id,
    name,
    industry: typeof x.industry === 'string' ? x.industry : typeof x.naics === 'string' ? x.naics : null,
    people: n(x.people),
    records: n(x.records),
    has_data: x.has_data === true,
    mail_domain: typeof x.mail_domain === 'string' ? x.mail_domain : null,
    timezone: typeof x.timezone === 'string' ? x.timezone : null,
    city: typeof x.city === 'string' ? x.city : null,
    api_url: typeof x.api_url === 'string' ? x.api_url : null,
    next_fit_at: typeof x.next_fit_at === 'string' ? x.next_fit_at : null,
    min_records: typeof x.min_records === 'number' ? x.min_records : null,
  };
}

const boardCache = new Map<string, Promise<BoardState>>();
const listeners = new Set<() => void>();

async function fetchBoard(id: string): Promise<BoardState> {
  try {
    const res = await fetch(boardApi(id), { headers: { accept: 'application/json' } });
    if (res.status === 404) {
      // a 404 from a router that has no such route is "endpoint missing", not "board missing"
      let body: unknown = null;
      try { body = await res.json(); } catch { /* no body */ }
      if (isObj(body) && typeof body.detail === 'string' && /no API route/i.test(body.detail)) return { kind: 'offline', error: 'GET /api/boards/{id} is not implemented by this API' };
      return { kind: 'missing' };
    }
    if (!res.ok) return { kind: 'offline', error: `HTTP ${res.status}` };
    const info = asBoardInfo(await res.json(), id);
    if (!info) return { kind: 'offline', error: 'unexpected shape from the API' };
    return { kind: 'data', board: info };
  } catch (e) {
    return { kind: 'offline', error: e instanceof Error ? e.message : String(e) };
  }
}

export function loadBoard(id: string, force = false): Promise<BoardState> {
  let p = force ? undefined : boardCache.get(id);
  if (!p) {
    p = fetchBoard(id);
    boardCache.set(id, p);
    p.then((r) => { if (r.kind === 'offline') setTimeout(() => boardCache.delete(id), 15000); });
  }
  return p;
}
/** After a write (new person, invite) the counts change: drop the cache and tell every subscriber. */
export function invalidateBoard(id: string) {
  boardCache.delete(id);
  listeners.forEach((l) => l());
}

/** GET /api/boards/{id} for the board on the URL. `null` while loading. */
export function useBoardInfo(): (BoardState & { retry: () => void }) | null {
  const { id } = useBoard();
  const [state, setState] = useState<BoardState | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    loadBoard(id).then((r) => { if (alive) setState(r); });
    const l = () => { if (alive) loadBoard(id).then((r) => { if (alive) setState(r); }); };
    listeners.add(l);
    return () => { alive = false; listeners.delete(l); };
  }, [id, tick]);
  // keep the previous value while a retry runs; `retry` forces a refetch
  const retry = useCallback(() => { boardCache.delete(id); setTick((t) => t + 1); }, [id]);
  return state ? { ...state, retry } : null;
}

/** The board's display name (falls back to the id while loading) and its industry words. */
export function useBoardName(): { name: string; industry: string; board: BoardInfo | null } {
  const { id } = useBoard();
  const s = useBoardInfo();
  const board = s?.kind === 'data' ? s.board : null;
  return { name: board?.name ?? id, industry: industryLabel(board?.industry), board };
}

// ---- board list ---------------------------------------------------------------------------------------------
export type BoardsState = { kind: 'data'; boards: BoardInfo[] } | { kind: 'offline'; error: string };

export function asBoardList(x: unknown): BoardInfo[] | null {
  const arr = Array.isArray(x) ? x : isObj(x) && Array.isArray(x.boards) ? x.boards : null;
  if (!arr) return null;
  return arr.map((b) => asBoardInfo(b, isObj(b) && typeof b.id === 'string' ? b.id : '')).filter((b): b is BoardInfo => !!b && !!b.id);
}

export async function fetchBoards(): Promise<BoardsState> {
  try {
    const res = await fetch('/api/boards', { headers: { accept: 'application/json' } });
    if (!res.ok) return { kind: 'offline', error: res.status === 404 ? 'GET /api/boards is not implemented by this API' : `HTTP ${res.status}` };
    const boards = asBoardList(await res.json());
    if (!boards) return { kind: 'offline', error: 'unexpected shape from the API' };
    return { kind: 'data', boards };
  } catch (e) {
    return { kind: 'offline', error: e instanceof Error ? e.message : String(e) };
  }
}

export function useBoards(): { state: BoardsState | null; reload: () => void } {
  const [state, setState] = useState<BoardsState | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    fetchBoards().then((r) => { if (alive) setState(r); });
    return () => { alive = false; };
  }, [tick]);
  return { state, reload: () => setTick((t) => t + 1) };
}

export interface NewBoard { name: string; industry: string; mail_domain: string; timezone: string }
export async function createBoard(b: NewBoard): Promise<{ ok: true; id: string } | { ok: false; error: string }> {
  try {
    const res = await fetch('/api/boards', { method: 'POST', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify(b) });
    let body: unknown = null;
    try { body = await res.json(); } catch { /* empty */ }
    if (!res.ok) return { ok: false, error: isObj(body) && typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}` };
    const id = isObj(body) ? (typeof body.id === 'string' ? body.id : typeof body.board_id === 'string' ? body.board_id : null) : null;
    if (!id) return { ok: false, error: 'the API did not return a board id' };
    return { ok: true, id };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
