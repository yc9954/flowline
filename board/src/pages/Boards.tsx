// "/" — every board this API serves (GET /api/boards), and the form that creates one (POST /api/boards).
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { createBoard, useBoards, type BoardInfo } from '../lib/board';
import { INDUSTRY_OPTIONS, industryLabel } from '../lib/industry';
import { int } from '../lib/format';
import { Logo } from '../components/Icons';
import './pages.css';

const TIMEZONES = [
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Anchorage', 'Pacific/Honolulu',
  'America/Toronto', 'America/Vancouver', 'America/Mexico_City', 'America/Sao_Paulo',
  'Europe/London', 'Europe/Dublin', 'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Amsterdam', 'Europe/Stockholm', 'Europe/Warsaw',
  'Asia/Seoul', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Singapore', 'Asia/Kolkata', 'Asia/Dubai', 'Australia/Sydney', 'Pacific/Auckland',
];

export default function BoardsPage() {
  const { state, reload } = useBoards();
  const [params] = useSearchParams();
  const [showNew, setShowNew] = useState(params.has('new'));
  useEffect(() => { document.title = 'Flowline — boards'; }, []);
  const boards = state?.kind === 'data' ? state.boards : [];
  // a company with nothing yet still shows up here, so the form opens by itself when the API has no boards at all
  const none = state?.kind === 'data' && boards.length === 0;

  return (
    <main className="boards">
      <div className="boards-head">
        <span className="sidebar-logo" style={{ width: 36, height: 36, borderRadius: 9 }}><Logo /></span>
        <div style={{ flex: 1 }}>
          <div className="label">Flowline · boards</div>
          <h1 className="headline" style={{ marginTop: 6, fontSize: 30 }}>{state ? (none ? 'No company yet.' : `${boards.length} ${boards.length === 1 ? 'company' : 'companies'} on this API.`) : 'Loading boards…'}</h1>
        </div>
        {!showNew && !none && <button type="button" className="btn-primary" onClick={() => setShowNew(true)}>New company</button>}
      </div>

      {state?.kind === 'offline' && (
        <div className="empty" style={{ padding: '8px 0' }} data-empty="offline">
          <div className="label">API offline</div>
          <p className="sub">The board list could not be loaded ({state.error}). Nothing here is made up.</p>
          <div className="empty-actions"><button type="button" className="btn-primary" onClick={reload}>Retry</button></div>
        </div>
      )}

      {boards.length > 0 && (
        <section aria-label="Boards" className="board-grid" data-board-list>
          {boards.map((b) => <BoardCard key={b.id} b={b} />)}
        </section>
      )}

      {(showNew || none) && <NewCompany onCreated={reload} onCancel={none ? undefined : () => setShowNew(false)} />}

      <p className="mono-11" style={{ marginTop: 8 }}>A board holds one company: its people's approved day records, the knowledge computed from them, and the plans it tests. Nothing on a board is typed in by hand.</p>
    </main>
  );
}

function BoardCard({ b }: { b: BoardInfo }) {
  const ind = industryLabel(b.industry);
  return (
    <Link to={`/b/${encodeURIComponent(b.id)}/know/waits`} className="board-card" data-board={b.id}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="name ellipsis">{b.name}</span>
        <span className={`chip ${b.has_data ? 'teal' : 'grey'}`} style={{ marginLeft: 'auto', flex: '0 0 auto' }}>{b.has_data ? 'has data' : 'no data yet'}</span>
      </div>
      <div className="mono-11">{[ind, b.city, b.mail_domain].filter(Boolean).join(' · ') || b.id}</div>
      <div className="counts">
        <div><div className="num">{int(b.people)}</div><div className="label-9">people</div></div>
        <div><div className="num">{int(b.records)}</div><div className="label-9">records</div></div>
      </div>
    </Link>
  );
}

function NewCompany({ onCreated, onCancel }: { onCreated: () => void; onCancel?: () => void }) {
  const nav = useNavigate();
  const localTz = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return 'America/Chicago'; } })();
  const [name, setName] = useState('');
  const [industry, setIndustry] = useState('');
  const [domain, setDomain] = useState('');
  const [tz, setTz] = useState(localTz);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const tzs = TIMEZONES.includes(localTz) ? TIMEZONES : [localTz, ...TIMEZONES];

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    const r = await createBoard({ name: name.trim(), industry, mail_domain: domain.trim().toLowerCase(), timezone: tz });
    setBusy(false);
    if (!r.ok) { setErr(r.error); return; }
    onCreated();
    nav(`/b/${encodeURIComponent(r.id)}/people`);
  }

  return (
    <form className="form-card primary" onSubmit={submit} aria-label="New company" data-new-company>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>New company</span>
        <span className="mono-11">one board per company · people are invited next</span>
      </div>
      <div className="form">
        <label className="field"><span className="label">Company name</span><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Harbor Dental" /></label>
        <label className="field"><span className="label">Industry (NAICS)</span>
          <select required value={industry} onChange={(e) => setIndustry(e.target.value)}>
            <option value="" disabled>Choose…</option>
            {INDUSTRY_OPTIONS.map((o) => <option key={o.naics} value={o.naics}>{o.label} · {o.naics}</option>)}
          </select>
        </label>
        <label className="field"><span className="label">Mail domain</span><input required value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="harbordental.com" pattern="[A-Za-z0-9.-]+\.[A-Za-z]{2,}" title="a domain like company.com" /></label>
        <label className="field"><span className="label">Timezone</span>
          <select value={tz} onChange={(e) => setTz(e.target.value)}>{tzs.map((z) => <option key={z} value={z}>{z}</option>)}</select>
        </label>
        <div className="form-foot">
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create board'}</button>
          {onCancel && <button type="button" className="btn lg" onClick={onCancel}>Cancel</button>}
          {err && <span className="confirm-line err">{err}</span>}
          <span className="mono-11" style={{ marginLeft: 'auto' }}>POST /api/boards</span>
        </div>
      </div>
    </form>
  );
}
