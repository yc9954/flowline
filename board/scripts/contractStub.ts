// Dev-only Vite middleware: the onboarding endpoints the board codes against (track G1's contract), served in memory
// until the API implements them. Every request is tried against the real API first; the stub answers only when the
// API says it has no such route. Boards created here live until the dev server restarts.
//
//   GET  /api/boards                       → { boards: [{ id, name, industry, people, records, has_data, … }] }
//   POST /api/boards                       { name, industry, mail_domain, timezone } → 201 { id, … }
//   GET  /api/boards/{id}                  → the board record
//   GET  /api/boards/{id}/people           → { people: [...] }
//   POST /api/boards/{id}/people           { name, role, email, target, skill_id, pre_approved } → 201 person
//   POST /api/boards/{id}/people/{pid}/invite → { invite_code, api_url }
//   GET  /api/boards/{id}/<anything else>  → 404 { state: "no_data_yet" } for a board created here (it has no model files)
//
// Disable with FLOWLINE_STUB=0.
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';

interface Person { id: string; name: string; role: string; email: string | null; target: string; skill_id: string | null; pre_approved: boolean; invite_status: 'not_invited' | 'invited' | 'joined'; invite_code: string | null; invited_at: string | null; joined_at: string | null }
interface Board { id: string; name: string; industry: string | null; mail_domain: string | null; timezone: string | null; city: string | null; has_data: boolean; created_at: string; people: Person[] }

const slug = (s: string) => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'board';
const code = () => { const A = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; let s = ''; for (let i = 0; i < 8; i++) s += A[Math.floor(Math.random() * A.length)]; return `${s.slice(0, 4)}-${s.slice(4)}`; };
const json = (res: ServerResponse, status: number, body: unknown) => { res.statusCode = status; res.setHeader('content-type', 'application/json'); res.end(JSON.stringify(body)); };
const readBody = (req: IncomingMessage) => new Promise<unknown>((resolve) => { let s = ''; req.on('data', (c: Buffer | string) => { s += c; }); req.on('end', () => { try { resolve(s ? JSON.parse(s) : {}); } catch { resolve({}); } }); });

export function contractStub(upstream: string): Plugin {
  const boards = new Map<string, Board>();
  // the demo board: the real API has its files; only the onboarding routes are stubbed for it
  const northwind: Board = { id: 'northwind', name: 'Northwind Fitness', industry: '713940', mail_domain: 'northwindfitness.com', timezone: 'America/Chicago', city: 'Austin, TX', has_data: true, created_at: '2026-09-01T00:00:00Z', people: [] };
  boards.set(northwind.id, northwind);

  async function upstreamJson(path: string): Promise<unknown | null> {
    try { const r = await fetch(upstream + path, { headers: { accept: 'application/json' } }); return r.ok ? await r.json() : null; } catch { return null; }
  }
  /** Does the real API serve this route? Probed with GET whatever the method (its 404 for an unknown route says "no API route for …"). */
  async function upstreamHas(path: string): Promise<boolean> {
    try {
      const r = await fetch(upstream + path, { headers: { accept: 'application/json' } });
      if (r.status !== 404) return true;
      const b = (await r.json().catch(() => null)) as { detail?: string } | null;
      return !(b && typeof b.detail === 'string' && /no API route/i.test(b.detail));
    } catch { return false; }
  }
  async function northwindPeople(): Promise<Person[]> {
    if (northwind.people.length) return northwind.people;
    const fleet = (await upstreamJson('/api/boards/northwind/fleet')) as { people?: { person: { id: string; name: string; role: string; target: string; skill_id: string; pre_approved: boolean } }[] } | null;
    northwind.people = (fleet?.people ?? []).map((r) => ({ id: r.person.id, name: r.person.name, role: r.person.role, email: null, target: r.person.target, skill_id: r.person.skill_id, pre_approved: r.person.pre_approved, invite_status: 'joined', invite_code: null, invited_at: null, joined_at: northwind.created_at }));
    return northwind.people;
  }
  async function record(b: Board, origin: string) {
    const people = b.id === 'northwind' ? await northwindPeople() : b.people;
    let records = 0;
    if (b.has_data) {
      const recs = await upstreamJson(`/api/boards/${b.id}/records`);
      records = Array.isArray(recs) ? recs.length : recs && typeof recs === 'object' && Array.isArray((recs as { records?: unknown }).records) ? (recs as { records: unknown[] }).records.length : 0;
      if (!records) { const ont = (await upstreamJson(`/api/boards/${b.id}/ontology`)) as { records_used?: number } | null; records = ont?.records_used ?? 0; }
    }
    return { id: b.id, name: b.name, industry: b.industry, mail_domain: b.mail_domain, timezone: b.timezone, city: b.city, people: people.length, records, has_data: b.has_data, api_url: origin, created_at: b.created_at, stub: true };
  }

  return {
    name: 'flowline-contract-stub',
    configureServer(server) {
      server.config.logger.info(`  contract stub: /api/boards, /people, /invite answered in memory when ${upstream} has no such route (FLOWLINE_STUB=0 disables)`);
      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://x');
        const m = url.pathname.match(/^\/api\/boards(?:\/([^/]+)(?:\/(.*))?)?$/);
        if (!m) return next();
        const method = (req.method ?? 'GET').toUpperCase();
        const [, rawId, rest = ''] = m;
        const id = rawId ? decodeURIComponent(rawId) : null;
        const origin = `${req.headers['x-forwarded-proto'] ?? 'http'}://${req.headers.host ?? 'localhost'}`;
        const stubRoute = !id || rest === '' || rest === 'people' || /^people\/[^/]+\/invite$/.test(rest);

        // a board that only exists here has no model files: everything but the onboarding routes is "no data yet"
        if (id && !stubRoute) {
          const b = boards.get(id);
          if (b && !b.has_data) return json(res, 404, { state: 'no_data_yet', detail: `board ${id} has no approved records yet` });
          if (!b && !(await upstreamHas(`/api/boards/${rawId}`))) {
            // the API does not know boards at all: anything but the demo board is unknown
            if (id !== 'northwind') return json(res, 404, { detail: `no board ${id}` });
          }
          return next();
        }
        if (!stubRoute) return next();
        // the real API wins whenever it has the route
        if (await upstreamHas(url.pathname)) return next();

        if (!id) {
          if (method === 'GET') return json(res, 200, { boards: await Promise.all([...boards.values()].map((b) => record(b, origin))) });
          if (method === 'POST') {
            const body = (await readBody(req)) as Partial<{ name: string; industry: string; mail_domain: string; timezone: string; city: string }>;
            if (!body.name?.trim()) return json(res, 422, { detail: 'name is required' });
            let bid = slug(body.name); let n = 2;
            while (boards.has(bid)) bid = `${slug(body.name)}-${n++}`;
            const b: Board = { id: bid, name: body.name.trim(), industry: body.industry ?? null, mail_domain: body.mail_domain ?? null, timezone: body.timezone ?? null, city: body.city ?? null, has_data: false, created_at: new Date().toISOString(), people: [] };
            boards.set(bid, b);
            return json(res, 201, await record(b, origin));
          }
          return json(res, 405, { detail: 'method not allowed' });
        }
        const b = boards.get(id);
        if (!b) return json(res, 404, { detail: `no board ${id}` });
        if (rest === '') return method === 'GET' ? json(res, 200, await record(b, origin)) : json(res, 405, { detail: 'method not allowed' });
        const people = b.id === 'northwind' ? await northwindPeople() : b.people;
        if (rest === 'people') {
          if (method === 'GET') return json(res, 200, { board_id: b.id, people });
          if (method === 'POST') {
            const body = (await readBody(req)) as Partial<{ name: string; role: string; email: string; target: string; skill_id: string; pre_approved: boolean }>;
            if (!body.name?.trim()) return json(res, 422, { detail: 'name is required' });
            const base = slug(`${body.role ?? 'person'}`) || 'person';
            let pid = `${base}-${people.length + 1}`; let k = people.length + 2;
            while (people.some((p) => p.id === pid)) pid = `${base}-${k++}`;
            const p: Person = { id: pid, name: body.name.trim(), role: body.role ?? 'Other', email: body.email ?? null, target: body.target ?? 'mac', skill_id: body.skill_id || null, pre_approved: body.pre_approved === true, invite_status: 'not_invited', invite_code: null, invited_at: null, joined_at: null };
            people.push(p);
            return json(res, 201, p);
          }
          return json(res, 405, { detail: 'method not allowed' });
        }
        const inv = rest.match(/^people\/([^/]+)\/invite$/);
        if (inv) {
          if (method !== 'POST') return json(res, 405, { detail: 'method not allowed' });
          const p = people.find((x) => x.id === decodeURIComponent(inv[1]));
          if (!p) return json(res, 404, { detail: `no person ${inv[1]} on board ${b.id}` });
          p.invite_code = code(); p.invite_status = 'invited'; p.invited_at = new Date().toISOString();
          return json(res, 200, { invite_code: p.invite_code, api_url: origin, person_id: p.id, expires_in_s: 7 * 86400 });
        }
        return next();
      });
    },
  };
}
