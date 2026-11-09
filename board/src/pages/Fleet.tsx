// /run/fleet — six people, six Linux desks, one plan. Live frames from the executor (every 500 ms), the run state
// from GET /api/boards/northwind/fleet (every 1 s). Click a card for the large view of that desk.
import { useCallback, useEffect, useRef, useState } from 'react';
import { API } from '../lib/api';
import { Kicker, PageHeader, Stamp } from '../components/Chrome';
import { EdgeGlow } from '../components/EdgeGlow';
import { Check } from '../components/Icons';
import './pages.css';
import './Fleet.css';

// ---- shapes (SCHEMA §11 + the fleet endpoint) -----------------------------------------------------------
interface Person { id: string; name: string; role: string; target: string; skill_id: string; pre_approved: boolean }
interface SuggestionLite { id: string; status: string; title: string; skill_id: string; run_id?: string | null; pre_approved?: boolean | null }
interface RunStep { n: number; label: string; detail: string; status: 'done' | 'now' | 'pending'; progress?: [number, number] | null; at_s?: number | null }
interface RunCheck { name: string; ok: boolean; detail: string }
interface RecentAction { at?: string; at_s?: number; kind?: string; text?: string; x?: number; y?: number }
interface Run {
  id: string; skill_id: string; target: string; status: 'running' | 'done' | 'stopped' | 'failed'; title?: string | null;
  started_at: string; elapsed_s: number; steps: RunStep[]; checks: RunCheck[]; last_action?: string | null; actions?: number; error?: string | null;
  recent_actions?: RecentAction[];
  pointer?: { x: number; y: number; at_s?: number; kind?: string } | null;  // last action with coordinates (survives the recent window)
}
type State = 'waiting' | 'running' | 'left_for_you' | 'stopped' | 'failed';
interface FleetRow { person: Person; suggestion: SuggestionLite | null; run: Run | null; state: State }
interface FleetEvent { at?: string; at_s?: number; kind?: string; text?: string; person_id: string; name: string; role: string; target: string }
interface Fleet {
  board_id: string; people: FleetRow[];
  counters: { running: number; done: number; failed: number; actions: number; actions_per_min: number; saved_without_review: number; stopped_by_people: number };
  events: FleetEvent[]; agent: string; fleet_enabled: boolean; skill_override?: string | null;
}

// one colour per desk, the glow's family: violet, blue, orange, teal, pink, lime
const DESK_COLOURS = ['#6D5BD0', '#3B73FF', '#FF5F1F', '#0F766E', '#E0409A', '#84CC16'];
const deskColour = (target: string) => DESK_COLOURS[(parseInt(target.replace(/\D/g, ''), 10) - 1 + DESK_COLOURS.length) % DESK_COLOURS.length] ?? DESK_COLOURS[0];
// the agent's coordinates live in its screenshot space (≤1280 wide; the bridge scales ×1.5 to the 1920×1080 desk)
const VIEW_W = 1280, VIEW_H = 720;
const STATE_LABEL: Record<State, string> = { waiting: 'waiting', running: 'running', left_for_you: 'left for you ✓', stopped: 'stopped', failed: 'failed' };
const demoGlow = () => typeof location !== 'undefined' && new URLSearchParams(location.search).has('glow');

// ---- polling ------------------------------------------------------------------------------------------------
function useFleet(intervalMs = 1000): { data: Fleet | null; error: string | null; at: Date | null } {
  const [data, setData] = useState<Fleet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState<Date | null>(null);
  useEffect(() => {
    let alive = true, timer = 0;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/fleet`, { headers: { accept: 'application/json' } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = (await res.json()) as Fleet;
        if (alive) { setData(d); setError(null); setAt(new Date()); }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
      if (alive) timer = window.setTimeout(poll, intervalMs);
    };
    poll();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [intervalMs]);
  return { data, error, at };
}

/** The board never shows a person's screen. Live frames exist only for the filming rig / development (?frames=1);
 *  by default a card shows a neutral tile — the glow and the step rail say that an agent is working, not what is on screen. */
const showFrames = () => typeof location !== 'undefined' && new URLSearchParams(location.search).has('frames');

function DeskPlaceholder({ role, state, big = false }: { role: string; state: State; big?: boolean }) {
  return (
    <div className={`frame placeholder ${big ? 'big' : ''}`} data-fleet-placeholder>
      <span className="ph-role">{role}</span>
      <span className="ph-note">{state === 'running' ? 'agent working on this desk' : state === 'left_for_you' ? 'left for the person to check' : 'screen stays on the desk'}</span>
    </div>
  );
}

/** Live frame (dev / filming only): fetches the JPEG every `every` ms and only swaps the <img> once the new frame has arrived. */
function LiveFrame({ target, width, every = 500, className = '' }: { target: string; width: number; every?: number; className?: string }) {
  const ref = useRef<HTMLImageElement>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let alive = true, timer = 0, busy = false, current: string | null = null;
    const grab = async () => {
      if (busy) return;
      busy = true;
      try {
        const res = await fetch(`/api/desk/${target}/frame.jpg?w=${width}&t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        if (!alive) return;
        const url = URL.createObjectURL(blob);
        const img = ref.current;
        if (img) {
          const prev = current;
          img.onload = () => { if (prev) URL.revokeObjectURL(prev); setLoaded(true); };
          img.src = url;
          current = url;
        }
      } catch { /* keep the previous frame */ } finally { busy = false; }
    };
    grab();
    timer = window.setInterval(grab, every);
    return () => { alive = false; window.clearInterval(timer); if (current) URL.revokeObjectURL(current); };
  }, [target, width, every]);
  return <img ref={ref} className={`frame ${loaded ? '' : 'empty'} ${className}`} alt={`${target} live`} draggable={false} />;
}

// ---- bits ---------------------------------------------------------------------------------------------------
const mmss = (s: number) => { const t = Math.max(0, Math.floor(s)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
const clock = (iso?: string) => { if (!iso) return ''; const d = new Date(iso); return isNaN(d.getTime()) ? '' : d.toTimeString().slice(0, 8); };

function StateChip({ state }: { state: State }) {
  return <span className={`chip state-chip state-${state}`} data-fleet-state={state}>{STATE_LABEL[state]}</span>;
}

function StepRail({ steps }: { steps: RunStep[] }) {
  return (
    <div className="step-rail" aria-label="steps">
      {steps.map((s, i) => (
        <span key={s.n} style={{ display: 'contents' }}>
          <span className={`dot ${s.status}`}>{s.status === 'done' ? <Check /> : null}</span>
          {i < steps.length - 1 && <span className={`seg ${s.status === 'done' ? (steps[i + 1].status === 'pending' ? 'half' : 'done') : ''}`} />}
        </span>
      ))}
    </div>
  );
}

function placeholderSteps(skill: string): RunStep[] {
  const labels = skill === 'fill_deck_from_sheet'
    ? ['READ THE SHEET', 'FILL THE DECK', 'CHECK THE TOTAL', 'LEAVE IT FOR YOU']
    : ['READ THE QUOTES', 'UPDATE THE SHEET', 'FILL THE DECK', 'EXPORT FOR SIGNATURE', 'LEAVE IT FOR YOU'];
  return labels.map((label, i) => ({ n: i + 1, label, detail: '', status: 'pending' as const }));
}

function currentStep(steps: RunStep[], run: Run | null): RunStep | null {
  const now = steps.find((s) => s.status === 'now');
  if (now) return now;
  if (run && run.status !== 'running') return steps[steps.length - 1] ?? null;
  return steps[0] ?? null;
}


/** Where the agent's pointer is: the newest recent action with coordinates, plus what it just did there. */
function pointerState(run: Run | null): { x: number; y: number; key: string; kind: string; typed?: string } | null {
  const acts = run?.recent_actions ?? [];
  let pos: RecentAction | null = null;
  for (let i = acts.length - 1; i >= 0; i--) { const a = acts[i]; if (a.x != null && a.y != null) { pos = a; break; } }
  if (!pos && run?.pointer) pos = { x: run.pointer.x, y: run.pointer.y, at_s: run.pointer.at_s, kind: run.pointer.kind };
  if (!pos) return null;
  // the newest desktop action decides the pulse / type-echo
  let last: RecentAction | null = null;
  for (let i = acts.length - 1; i >= 0; i--) { if ((acts[i].kind ?? '').startsWith('computer.')) { last = acts[i]; break; } }
  const kind = (last?.kind ?? '').replace('computer.', '');
  const typed = kind === 'type' ? (last?.text ?? '').replace(/^type\s*/, '').replace(/^"|"$/g, '') : undefined;
  return { x: pos.x!, y: pos.y!, key: `${last?.at_s ?? ''}-${last?.kind ?? ''}`, kind, typed };
}

/** ?glow=1: a stand-in run with one click per desk, so pointers can be recorded without live runs. */
function demoRun(target: string): Run {
  const n = parseInt(target.replace(/\D/g, ''), 10) || 1;
  const x = 300 + ((n * 173) % 700), y = 160 + ((n * 97) % 420);
  return { id: `demo-${target}`, skill_id: 'demo', target, status: 'running', started_at: '', elapsed_s: 0, steps: [], checks: [],
    recent_actions: [{ at_s: n, kind: 'computer.left_click', text: `left_click ${x},${y}`, x, y }] };
}

/** Labelled agent pointer over a live frame (multiplayer-canvas style). Transform/opacity only. */
function AgentCursor({ run, role, target, visible, size = 18 }: { run: Run | null; role: string; target: string; visible: boolean; size?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [echo, setEcho] = useState<string | null>(null);
  const [pulse, setPulse] = useState(0);
  const seen = useRef<string>('');
  const p = pointerState(run);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver((es) => { const b = es[0]?.contentRect; if (b) setDims({ w: b.width, h: b.height }); });
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!p || p.key === seen.current) return;
    seen.current = p.key;
    if (p.kind.endsWith('click')) setPulse((n) => n + 1);
    if (p.typed) { setEcho(p.typed); const id = window.setTimeout(() => setEcho(null), 1500); return () => window.clearTimeout(id); }
  }, [p?.key]); // eslint-disable-line react-hooks/exhaustive-deps
  const colour = deskColour(target);
  const show = visible && !!p && dims.w > 0;
  const x = p ? (p.x / VIEW_W) * dims.w : 0, y = p ? (p.y / VIEW_H) * dims.h : 0;
  const flip = p ? p.x / VIEW_W > 0.5 : false;  // the pill is ~140 px wide at card scale
  return (
    <div ref={box} className="cursor-layer" aria-hidden="true" data-fleet-cursor={show ? 'on' : 'off'}>
      <div className={`cursor ${flip ? 'flip' : ''}`} style={{ transform: `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`, opacity: show ? 1 : 0, ['--c' as string]: colour }}>
        {pulse > 0 && <span key={pulse} className="ring" style={{ width: size * 1.8, height: size * 1.8 }} />}
        <svg className="arrow" width={size} height={size} viewBox="0 0 18 18"><path d="M2 1.5 L15.5 9 L9.3 10.3 L6.2 16.2 Z" fill={colour} stroke="#fff" strokeWidth="1.4" strokeLinejoin="round" /></svg>
        <span className={`pill ${echo ? 'echo' : ''}`} style={{ left: flip ? undefined : size * 0.9, right: flip ? size * 0.2 : undefined, top: size * 0.95, fontSize: size >= 24 ? 13 : 11 }}>{echo ? echo : <>Flowline · {role}</>}</span>
      </div>
    </div>
  );
}

function DeskCard({ row, glow, onOpen }: { row: FleetRow; glow: boolean; onOpen: () => void }) {
  const { person, run, state, suggestion } = row;
  const steps = run?.steps?.length ? run.steps : placeholderSteps(person.skill_id);
  const cur = currentStep(steps, run);
  const done = steps.filter((s) => s.status === 'done').length;
  const title = run?.title ?? suggestion?.title?.replace(/\?$/, '') ?? '—';
  const frameState = state === 'left_for_you' ? 'done' : state;
  return (
    <button type="button" className={`fleet-card is-${frameState}`} data-fleet-card data-target={person.target} data-person={person.id} data-state={state} onClick={onOpen} aria-label={`${person.name}, ${person.role}, ${person.target}: ${STATE_LABEL[state]}`}>
      <div className={`frame-wrap ${frameState}`}>
        {showFrames() ? <LiveFrame target={person.target} width={960} /> : <DeskPlaceholder role={person.role} state={state} />}
        <EdgeGlow active={glow} thickness={26} />
        {showFrames() && <AgentCursor run={run ?? (glow ? demoRun(person.target) : null)} role={person.role} target={person.target} visible={glow || state === 'running'} size={18} />}
        <span className="desk-tag">{person.target}</span>
        <StateChip state={state} />
      </div>
      <div className="fleet-who">
        <span className="role">{person.role}</span>
        <span className="name">{person.name}</span>
        <span className="elapsed" data-fleet-elapsed>{run ? mmss(run.elapsed_s) : suggestion?.pre_approved ? 'pre-approved' : state === 'waiting' ? (suggestion ? 'offered' : '—') : ''}</span>
      </div>
      <div className="fleet-title" title={title}>{title}</div>
      <StepRail steps={steps} />
      <div className="step-line">
        <span className="n">{cur ? `${cur.n}/${steps.length}` : ''}</span>
        <span className="label mono" style={{ fontSize: 10.5, letterSpacing: '0.6px', textTransform: 'uppercase', fontWeight: 600 }}>{cur?.label ?? ''}</span>
        <span className="prog">{cur?.progress ? `${cur.progress[0]} / ${cur.progress[1]}` : `${done} of ${steps.length} done`}</span>
      </div>
      <div className="last-action" data-fleet-last-action>
        {run?.last_action ? <>{run.last_action}<span className="dim"> · {run.actions ?? 0} actions</span></> : <span className="dim">{state === 'waiting' ? 'no run yet' : run?.error ? run.error.slice(0, 80) : 'starting…'}</span>}
      </div>
    </button>
  );
}

function BigView({ row, events, glow, onClose }: { row: FleetRow; events: FleetEvent[]; glow: boolean; onClose: () => void }) {
  const { person, run, state, suggestion } = row;
  const steps = run?.steps?.length ? run.steps : placeholderSteps(person.skill_id);
  const frameState = state === 'left_for_you' ? 'done' : state;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const mine = events.filter((e) => e.person_id === person.id).slice(0, 14);
  return (
    <div className="fleet-big" data-fleet-big data-target={person.target} role="dialog" aria-label={`${person.target} — ${person.name}`}>
      <div className="stage">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span className="label">{person.target} · {person.role}</span>
          <span style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>{person.name}</span>
          <span className="mono-11" style={{ marginLeft: 'auto' }}>{run ? `${mmss(run.elapsed_s)} · ${run.actions ?? 0} actions` : ''}</span>
          <StateChip state={state} />
        </div>
        <div className={`frame-wrap ${frameState}`}>
          {showFrames() ? <LiveFrame target={person.target} width={1920} /> : <DeskPlaceholder role={person.role} state={state} big />}
          <EdgeGlow active={glow} thickness={70} />
          {showFrames() && <AgentCursor run={run ?? (glow ? demoRun(person.target) : null)} role={person.role} target={person.target} visible={glow || state === 'running'} size={26} />}
        </div>
        <div className="last-action" style={{ fontSize: 12 }}>{run?.last_action ?? <span className="dim">no action yet</span>}</div>
      </div>
      <aside className="side" data-fleet-rail>
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Run</div>
          <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>{run?.title ?? suggestion?.title ?? '—'}</div>
          <div className="mono-11" style={{ marginTop: 4 }}>{run ? `${run.skill_id} · ${run.id}` : suggestion ? `${suggestion.skill_id} · ${suggestion.status}` : person.skill_id}</div>
        </div>
        <ol className="steps-v">
          {steps.map((s) => (
            <li key={s.n}>
              <span className={`dot ${s.status}`} style={{ borderRadius: '50%', border: '1.5px solid var(--rule)', display: 'flex', alignItems: 'center', justifyContent: 'center', background: s.status === 'done' ? '#171717' : s.status === 'now' ? '#FCBB00' : '#fff', borderColor: s.status === 'done' ? '#171717' : s.status === 'now' ? '#e0a800' : undefined }}>{s.status === 'done' ? <Check /> : null}</span>
              <div style={{ minWidth: 0 }}>
                <div className={`lbl ${s.status}`}>{s.label}</div>
                {s.detail && <div className="det">{s.detail}</div>}
              </div>
              <span className="mono-10">{s.progress ? `${s.progress[0]}/${s.progress[1]}` : s.at_s != null ? mmss(s.at_s) : ''}</span>
            </li>
          ))}
        </ol>
        {run && run.checks.length > 0 && (
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Checks · {run.checks.filter((c) => c.ok).length}/{run.checks.length}</div>
            <div className="checks">
              {run.checks.map((c) => (
                <div key={c.name} className="check"><span className="sq" style={{ background: c.ok ? 'var(--teal)' : 'var(--rust)' }} /><span style={{ flex: 1, minWidth: 0 }}>{c.name.replace(/_/g, ' ')}<span className="muted"> · {c.detail.slice(0, 60)}</span></span></div>
              ))}
            </div>
          </div>
        )}
        <div className="fleet-events">
          <div className="head"><span className="live-dot" />this desk</div>
          <ol>
            {mine.length === 0 && <li className="none">nothing yet</li>}
            {mine.map((e, i) => <li key={i}><span className="t">{e.at_s != null ? mmss(e.at_s) : ''}</span><span className="who">{e.kind === 'step' ? 'step' : 'do'}</span><span className={`what ${e.kind === 'step' ? 'step' : ''}`}>{e.text}</span></li>)}
          </ol>
        </div>
      </aside>
      <button type="button" className="btn sm close" onClick={onClose}>Close · Esc</button>
    </div>
  );
}

// ---- page ---------------------------------------------------------------------------------------------------
export default function FleetPage() {
  const { data, error, at } = useFleet(1000);
  const [open, setOpen] = useState<string | null>(null);
  const close = useCallback(() => setOpen(null), []);
  const demo = demoGlow();
  if (!data) {
    return (
      <main className="main canvas">
        <PageHeader crumbs={[{ label: 'Northwind Fitness' }, { label: 'Client proposals', to: '/know/waits' }, { label: 'Agents on desks' }]} stamp={<Stamp origin={error ? 'fixture' : 'api'} error={error ?? undefined} label="live" />} />
        <div className="loading">{error ? `fleet API offline (${error}) — start the API with FLOWLINE_FLEET=1` : 'connecting to the fleet…'}</div>
      </main>
    );
  }
  const c = data.counters;
  const rows = data.people;
  const big = open ? rows.find((r) => r.person.target === open) ?? null : null;
  const headline = c.running > 0
    ? `${c.running} ${c.running === 1 ? 'desk is' : 'desks are'} working. ${c.done > 0 ? `${c.done} left for people to check.` : 'Nothing is saved until someone looks.'}`
    : c.done > 0
      ? `${c.done} of ${rows.length} runs left for people to check. Nothing was saved by an agent.`
      : 'Six people, six desks, one yes.';
  return (
    <main className="main canvas" style={{ minHeight: '100vh' }}>
      <PageHeader crumbs={[{ label: 'Northwind Fitness' }, { label: 'Client proposals', to: '/know/waits' }, { label: 'Agents on desks' }]} stamp={<Stamp origin={error ? 'fixture' : 'api'} error={error ?? undefined} at={at ?? undefined} label="live" extra={data.skill_override ? `override ${data.skill_override}` : undefined} />} />
      <div>
        <Kicker>Run · agents on desks · {rows.length} people · {data.fleet_enabled ? 'pre-approved runs start together' : 'one run at a time'}</Kicker>
        <h1 className="headline" style={{ marginTop: 10, fontSize: 26 }} data-fleet-headline>{headline}</h1>
      </div>

      <div className="fleet-layout">
        <section className="fleet-grid" data-fleet-grid aria-label="Six desks">
          {rows.map((r) => <DeskCard key={r.person.id} row={r} glow={demo || r.state === 'running'} onOpen={() => setOpen(r.person.target)} />)}
        </section>

        <aside className="fleet-rail" data-fleet-rail aria-label="Live events and counters">
          <div className="fleet-counters">
            <div className="stat" data-fleet-counter="running"><span className="label">Running</span><span className="v">{c.running}</span><span className="s">of {rows.length} desks</span></div>
            <div className="stat" data-fleet-counter="done"><span className="label">Left for you</span><span className="v">{c.done}</span><span className="s">{c.failed ? `${c.failed} failed` : 'nothing saved'}</span></div>
            <div className="stat soft" data-fleet-counter="actions"><span className="label">Actions</span><span className="v">{c.actions}</span><span className="s">{c.actions_per_min} / min</span></div>
            <div className="stat soft" data-fleet-counter="saved"><span className="label">Saved w/o review</span><span className="v">{c.saved_without_review}</span><span className="s">by design</span></div>
            <div className="stat soft" data-fleet-counter="stopped"><span className="label">Stopped by people</span><span className="v">{c.stopped_by_people}</span><span className="s">one click, any time</span></div>
          </div>
          <div className="fleet-events" data-fleet-events>
            <div className="head"><span className="live-dot" />live · newest first</div>
            <ol>
              {data.events.length === 0 && <li className="none">No actions yet — approve the plan, then say yes once.</li>}
              {data.events.map((e, i) => (
                <li key={`${e.person_id}-${e.at ?? ''}-${i}`}>
                  <span className="t">{clock(e.at) || (e.at_s != null ? mmss(e.at_s) : '')}</span>
                  <span className="who" title={e.name}>{e.target}</span>
                  <span className={`what ${e.kind === 'step' ? 'step' : ''}`} title={e.text}>{e.text}</span>
                </li>
              ))}
            </ol>
          </div>
          <div className="fleet-foot" data-fleet-foot>agents: {data.agent} · screenshots stay on the desk</div>
        </aside>
      </div>

      {big && <BigView row={big} events={data.events} glow={demo || big.state === 'running'} onClose={close} />}
    </main>
  );
}
