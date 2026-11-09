// /b/:boardId/people — who is on the board, add a person, issue the invite code they enter in the Mac app.
import { useState, type FormEvent } from 'react';
import { addPerson, asPeople, forgetPeople, issueInvite, usePeople, type Person } from '../lib/api';
import { invalidateBoard, useBoard, useBoardName } from '../lib/board';
import { dayTime, roleLabel } from '../lib/format';
import { Kicker, Loading, PageHeader, Stamp, Verdict, NextLink } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import { Check } from '../components/Icons';
import './pages.css';

const ROLES = ['Sales', 'PM', 'Design', 'Finance', 'Director', 'Legal', 'Ops', 'BranchMgr', 'CEO', 'Trainer', 'Other'];
const CRUMBS = [{ label: 'Run' }, { label: 'People & invites' }];

/** The address a person types into the Mac app: the board's api_url if the API knows it, else where this page is served from. */
const apiAddress = (fromBoard?: string | null) => fromBoard || (typeof location !== 'undefined' ? location.origin : '');
export const joinLink = (api: string, code: string) => `flowline://join?api=${encodeURIComponent(api)}&code=${encodeURIComponent(code)}`;

export default function PeoplePage() {
  const { api, id } = useBoard();
  const { board } = useBoardName();
  const res = usePeople();
  const [tick, setTick] = useState(0);
  const [invites, setInvites] = useState<Record<string, { code: string; api: string }>>({});
  const [issuing, setIssuing] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!res) return <main className="main"><Loading what="people" /></main>;
  // "no_data_yet" is about records; the people list is a plain list, so an empty board still renders the page
  if (res.kind === 'offline' || (res.kind === 'empty' && res.state === 'no_such_board')) return <NotReady res={res} crumbs={CRUMBS} what="people" />;
  const people = res.kind === 'data' ? asPeople(res.data) : [];
  const address = apiAddress(board?.api_url);
  const joined = people.filter((p) => p.invite_status === 'joined').length;
  const invited = people.filter((p) => p.invite_status !== 'not_invited').length;

  const refresh = () => { forgetPeople(api); invalidateBoard(id); res.retry(); setTick((t) => t + 1); };

  async function invite(p: Person) {
    setIssuing(p.id); setErr(null);
    const r = await issueInvite(api, p.id);
    setIssuing(null);
    if (!r.ok) { setErr(r.status === 0 ? 'API offline — no invite was issued.' : `The API answered ${r.status} (${r.error}); no invite was issued.`); return; }
    const code = r.body?.invite_code;
    if (!code) { setErr('The API returned no invite_code.'); return; }
    setInvites((m) => ({ ...m, [p.id]: { code, api: r.body?.api_url || address } }));
    forgetPeople(api); invalidateBoard(id);
  }

  return (
    <main className="main">
      <PageHeader crumbs={CRUMBS} stamp={<Stamp origin={res.kind === 'data' ? res.origin : 'api'} at={res.kind === 'data' ? res.fetchedAt : undefined} label="fetched" />} />
      <div>
        <Kicker>Onboarding · {people.length} {people.length === 1 ? 'person' : 'people'} · {invited} invited · {joined} joined</Kicker>
        <div className="headline-row">
          <h1 className="headline">{people.length === 0 ? 'Nobody on this board yet.' : `${people.length} ${people.length === 1 ? 'person' : 'people'}, each with their own invite.`}</h1>
        </div>
        <p className="sub" style={{ maxWidth: 680 }}>A person joins from their own Mac with a one-time code. The app records their day locally; only the record they approve reaches this board.</p>
      </div>

      <section aria-label="People" className="table people" data-people>
        <div className="thead people-cols"><span>Name</span><span>Role</span><span>Email</span><span>Target</span><span>Pre-approved</span><span>Invite</span><span /></div>
        {people.length === 0 && <div className="trow" style={{ gridTemplateColumns: '1fr', height: 44, color: 'var(--muted)', fontSize: 13 }}>Add the first person below.</div>}
        {people.map((p) => {
          const inv = invites[p.id] ?? (p.invite_code ? { code: p.invite_code, api: address } : null);
          return (
            <div key={p.id} style={{ display: 'contents' }}>
              <div className="trow people-cols" data-person={p.id}>
                <span style={{ fontSize: 14, fontWeight: 500 }} className="ellipsis">{p.name}<span className="mono-10"> · {p.id}</span></span>
                <span style={{ fontSize: 13 }}>{roleLabel(p.role)}</span>
                <span className="mono-11 ellipsis" title={p.email ?? ''}>{p.email || '—'}</span>
                <span className="mono-12">{p.target === 'mac' ? 'their own Mac' : p.target}</span>
                <span>{p.pre_approved ? <span className="chip teal">yes</span> : <span className="chip grey">asks first</span>}</span>
                <span>
                  {p.invite_status === 'joined' ? <span className="chip teal" style={{ gap: 4 }}><Check size={9} stroke="#0b5f58" />joined{p.joined_at ? ` ${dayTime(p.joined_at)}` : ''}</span>
                    : p.invite_status === 'invited' || inv ? <span className="chip amber">invited{p.invited_at ? ` ${dayTime(p.invited_at)}` : ''}</span>
                      : <span className="chip grey">not invited</span>}
                </span>
                <span style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  {p.invite_status !== 'joined' && (
                    <button type="button" className="btn xs" disabled={issuing === p.id} onClick={() => invite(p)}>{issuing === p.id ? 'Issuing…' : inv ? 'New code' : 'Issue invite'}</button>
                  )}
                </span>
              </div>
              {inv && p.invite_status !== 'joined' && <InviteCard code={inv.code} api={inv.api} name={p.name} />}
            </div>
          );
        })}
      </section>
      {err && <div className="confirm-line err">{err}</div>}

      <AddPerson key={tick} api={api} onAdded={refresh} />

      <Verdict strong="Nothing is collected until a person approves it." rest="The invite only pairs a Mac with this board; the day record stays on the machine until the person says yes at 18:00.">
        <NextLink to="/run/fleet">Agents on desks</NextLink>
      </Verdict>
    </main>
  );
}

function InviteCard({ code, api, name }: { code: string; api: string; name: string }) {
  const [copied, setCopied] = useState<'code' | 'link' | null>(null);
  const link = joinLink(api, code);
  const copy = (what: 'code' | 'link', text: string) => { navigator.clipboard?.writeText(text).then(() => { setCopied(what); setTimeout(() => setCopied(null), 1500); }); };
  return (
    <div className="trow" style={{ gridTemplateColumns: 'auto minmax(0, 1fr)', columnGap: 20, padding: '12px 14px 14px', background: '#fffcf5', alignItems: 'start' }} data-invite={code}>
      <div>
        <div className="label">Invite code · {name}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
          <span className="invite-code">{code}</span>
          <button type="button" className="btn xs" onClick={() => copy('code', code)}>{copied === 'code' ? 'Copied' : 'Copy'}</button>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
        <div style={{ fontSize: 13, lineHeight: '20px' }}>Open Flowline on your Mac → Settings → Join a company → enter this code and the API address <span className="mono-12">{api}</span>.</div>
        <div className="invite-link">
          <code title={link}>{link}</code>
          <button type="button" className="btn xs" onClick={() => copy('link', link)}>{copied === 'link' ? 'Copied' : 'Copy link'}</button>
        </div>
      </div>
    </div>
  );
}

function AddPerson({ api, onAdded }: { api: string; onAdded: () => void }) {
  const [name, setName] = useState('');
  const [role, setRole] = useState('Sales');
  const [email, setEmail] = useState('');
  const [target, setTarget] = useState('mac');
  const [desk, setDesk] = useState(1);
  const [skill, setSkill] = useState('');
  const [pre, setPre] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null); setDone(null);
    const r = await addPerson(api, { name: name.trim(), role, email: email.trim(), target: target === 'desk' ? `desk${desk}` : 'mac', skill_id: skill.trim(), pre_approved: pre });
    setBusy(false);
    if (!r.ok) { setErr(r.status === 0 ? 'API offline — nobody was added.' : `The API answered ${r.status} (${r.error}); nobody was added.`); return; }
    setDone(`${name.trim()} added. Issue their invite above.`);
    setName(''); setEmail(''); setSkill(''); setPre(false);
    onAdded();
  }

  return (
    <form className="form-card" onSubmit={submit} aria-label="Add a person" data-add-person>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Add a person</span>
        <span className="mono-11">POST {api}/people</span>
      </div>
      <div className="form">
        <label className="field"><span className="label">Name</span><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" /></label>
        <label className="field"><span className="label">Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}</select>
        </label>
        <label className="field"><span className="label">Email</span><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" /></label>
        <label className="field"><span className="label">Target</span>
          <span style={{ display: 'flex', gap: 6 }}>
            <select value={target} onChange={(e) => setTarget(e.target.value)} style={{ flex: 1 }}><option value="mac">their own Mac</option><option value="desk">a Linux desk</option></select>
            {target === 'desk' && <input type="number" min={1} max={99} value={desk} onChange={(e) => setDesk(Math.max(1, Number(e.target.value) || 1))} style={{ width: 64 }} aria-label="desk number" />}
          </span>
        </label>
        <label className="field"><span className="label">Skill offered</span><input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="e.g. fill_deck_from_sheet" /></label>
        <label className="field check"><input type="checkbox" checked={pre} onChange={(e) => setPre(e.target.checked)} /><span>Pre-approved: runs start on the first yes</span></label>
        <div className="form-foot">
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Adding…' : 'Add person'}</button>
          {err && <span className="confirm-line err">{err}</span>}
          {done && <span className="confirm-line"><Check size={11} stroke="#0F766E" />{done}</span>}
        </div>
      </div>
    </form>
  );
}
