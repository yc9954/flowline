import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { asRecordList, useRecords, withdrawRecord } from '../lib/api';
import { dayMonYear, hhmm, hhmmss, hoursMinutes, longDate, roleLabel } from '../lib/format';
import type { WorkRecord } from '../lib/types';
import { AskWhy, Kicker, Loading, DataStamp, NextLink, PageHeader, SourceChip, Verdict } from '../components/Chrome';
import { Check, ShieldCheck } from '../components/Icons';
import './Records.css';

export default function RecordsPage() {
  const res = useRecords();
  const { id } = useParams();
  const nav = useNavigate();
  if (!res) return <main className="main"><Loading what="records" /></main>;
  const records = asRecordList(res.data).slice().sort((a, b) => (a.approved_at < b.approved_at ? 1 : -1));
  const open = id ? records.find((r) => r.id === id) : undefined;
  const people = new Set(records.map((r) => r.person_id)).size;
  const days = new Set(records.map((r) => r.date)).size;
  const hands = records.reduce((a, r) => a + r.hands_on_min, 0), waits = records.reduce((a, r) => a + r.waiting_min, 0);
  const source = res.origin === 'fixture' ? 'prototype' : 'measured';

  return (
    <main className="main">
      <SourceChip source={source} />
      <PageHeader crumbs={[{ label: 'Northwind Fitness' }, { label: 'Know' }, { label: 'Approved records' }]} stamp={<DataStamp res={res} data={{}} />} />

      <div>
        <Kicker>Approved records · {records.length} on the board · {people} people · {days} days</Kicker>
        <div className="headline-row">
          <h1 className="headline">{records.length} records, each approved by the person it describes.</h1>
          <AskWhy source={source} lines={[
            `${records.length} signed day records from ${people} people over ${days} days`,
            `${hoursMinutes(hands)} hands-on and ${hoursMinutes(waits)} waiting, as the people themselves approved it`,
            'Each record is hashed (SHA-256) and signed on the person’s own machine (ed25519); the API rejects a record whose signature does not verify.',
          ]} />
        </div>
        <p className="sub">Steps, times and hand-offs only — never screens, messages or files. Click a day to open the record.</p>
      </div>

      <section aria-label="Approved records" className="paper">
        <div className="paper-head">
          <span>No.</span><span>Person</span><span>Day</span><span className="right">Steps</span><span className="right">Hands-on</span><span className="right">Waiting</span><span className="right">Private</span><span className="right">Approved</span><span className="right">Proof</span>
        </div>
        {records.length === 0 && <div className="paper-row muted" style={{ gridTemplateColumns: '1fr' }}>No approved records yet. Records arrive each evening after the end-of-day review.</div>}
        {records.map((r) => (
          <Link key={r.id} to={`/know/records/${r.id}`} className="paper-row">
            <span className="mono-11">{r.id}</span>
            <span><strong>{roleLabel(r.role)}</strong> <span className="mono-10">· {r.person_id}</span></span>
            <span>{longDate(r.date)}</span>
            <span className="num right">{r.steps.length}</span>
            <span className="mono-11 right" style={{ color: '#151515' }}>{hoursMinutes(r.hands_on_min)}</span>
            <span className="mono-11 right" style={{ color: r.waiting_min > 0 ? '#6b4a00' : undefined }}>{hoursMinutes(r.waiting_min)}</span>
            <span className="mono-11 right">{r.kept_private} item{r.kept_private === 1 ? '' : 's'}</span>
            <span className="mono-11 right">{hhmm(r.approved_at)}</span>
            <span className="right"><span className="chip teal" style={{ gap: 4 }}><Check size={9} stroke="#0b5f58" />verified</span></span>
          </Link>
        ))}
      </section>

      <Verdict strong="Only approved records reach the board." rest="Withdraw takes a record off the board any time; the steps stay on the person’s machine.">
        <NextLink to="/know/knowledge">See what they add up to</NextLink>
      </Verdict>

      {open && <RecordSheet r={open} onClose={() => nav('/know/records')} />}
    </main>
  );
}

function RecordSheet({ r, onClose }: { r: WorkRecord; onClose: () => void }) {
  const [state, setState] = useState<'idle' | 'confirm' | 'busy' | 'done' | 'error'>('idle');
  const [msg, setMsg] = useState('');
  const [copied, setCopied] = useState(false);
  const steps = [...r.steps].sort((a, b) => a.idx - b.idx);
  const total = r.hands_on_min + r.waiting_min;
  const took = (s: WorkRecord['steps'][number]) => Math.round((new Date(s.end).getTime() - new Date(s.start).getTime()) / 60000);
  const short = (h: string) => (h.length > 16 ? `${h.slice(0, 8)}…${h.slice(-6)}` : h);
  async function withdraw() {
    setState('busy');
    const res = await withdrawRecord(r.id);
    if (res.ok) { setState('done'); setMsg('Withdrawn. The record is off the board; the steps stay on the device.'); }
    else { setState('error'); setMsg(res.status === 0 ? 'API offline — nothing was withdrawn.' : `The API answered ${res.status}; nothing was withdrawn.`); }
  }
  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div className="sheet" role="dialog" aria-label={`Work record ${r.id}`} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-shadow" aria-hidden="true" />
        <section className="sheet-paper">
          <div style={{ padding: '26px 32px 18px', display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <span style={{ flex: '0 0 44px', width: 44, height: 44, borderRadius: '50%', background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><ShieldCheck /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="p-label" style={{ fontSize: 10, display: 'flex', gap: 8 }}><span>Flowline work record</span><span>·</span><span>No. {r.id}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.025em', lineHeight: '30px' }}>{roleLabel(r.role)} · {longDate(r.date)}</span>
                <span className="chip teal" style={{ height: 22, fontSize: 10, padding: '0 8px', gap: 6, color: '#0b5f58' }}><Check size={11} stroke="#0b5f58" />Approved by {r.person_id} · {hhmm(r.approved_at)}</span>
              </div>
              <p style={{ margin: '6px 0 0', fontSize: 14, lineHeight: '22px', color: 'rgba(0,0,0,0.62)' }}>This record is all the team’s board can see from that day. Nothing else from that machine is shared.</p>
            </div>
            <button type="button" aria-label="Close record" className="sheet-x" onClick={onClose}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg></button>
          </div>

          <div className="p-meta">
            <div><span className="p-label">Board</span>&nbsp; {r.board_id === 'northwind' ? 'Northwind Fitness board' : r.board_id}</div>
            <div><span className="p-label">Role</span>&nbsp; {roleLabel(r.role)}</div>
            <div><span className="p-label">Covers</span>&nbsp; {hhmm(r.covers.start)}–{hhmm(r.covers.end)}</div>
            <div style={{ textAlign: 'right' }}><span className="p-label">Approved</span>&nbsp; {dayMonYear(r.approved_at)} · {hhmmss(r.approved_at)}</div>
          </div>

          <div className="p-stats">
            <div><div className="p-label">Steps</div><div className="p-big">{steps.length}</div></div>
            <div><div className="p-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="sq" style={{ background: '#30373f' }} />Hands-on</div><div className="p-big">{hoursMinutes(r.hands_on_min)}</div></div>
            <div><div className="p-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="sq" style={{ background: '#FCBB00' }} />Waiting on others</div><div className="p-big">{hoursMinutes(r.waiting_min)}</div></div>
            <div><div className="p-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="rgba(0,0,0,0.58)" strokeWidth="2.4" strokeLinecap="round"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>Kept private</div><div className="p-big">{r.kept_private} item{r.kept_private === 1 ? '' : 's'}</div></div>
          </div>

          <div style={{ padding: '4px 32px 0' }}>
            <div className="p-label" style={{ display: 'flex', padding: '10px 0', borderBottom: '1px solid rgba(0,0,0,0.12)' }}><span>{steps.length} steps shared</span><span style={{ marginLeft: 'auto' }}>Took</span></div>
            {steps.map((s, i) => (
              <div key={s.idx} style={{ padding: '12px 0', borderTop: i ? '1px solid rgba(0,0,0,0.08)' : 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span className="mono" style={{ width: 22, fontSize: 10, letterSpacing: 1, color: 'rgba(0,0,0,0.58)' }}>{String(s.idx).padStart(2, '0')}</span>
                  <span style={{ fontSize: 15, fontWeight: 500 }}>{s.name}</span>
                  {s.kind === 'waiting' && <span className="chip amber">Waiting</span>}
                  {s.repeats != null && s.repeats > 1 && <span className="chip violet">Repeats</span>}
                  <span className="p-dots" />
                  <span className="mono" style={{ fontSize: 13, fontVariantNumeric: 'tabular-nums', color: s.kind === 'waiting' ? '#6b4a00' : '#151515', fontWeight: s.kind === 'waiting' ? 600 : 400 }}>{hoursMinutes(took(s))}</span>
                </div>
                <div className="p-cols">
                  <div><div className="p-label">Case</div><div className="p-val">{s.case_id ?? '—'}</div></div>
                  <div><div className="p-label">Tools</div><div className="p-val">{s.tools.length ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>{s.tools.map((t) => <ToolDot key={t} tool={t} />)}<span>{s.tools.join(' → ')}</span></span> : '—'}</div></div>
                  <div><div className="p-label">Handed from / to</div><div className="p-val">{s.handoff_from || s.handoff_to ? `${s.handoff_from ? roleLabel(s.handoff_from) : roleLabel(r.role)} → ${s.handoff_to ? roleLabel(s.handoff_to) : roleLabel(r.role)}` : '—'}</div></div>
                  <div><div className="p-label">Waiting on</div><div className="p-val">{s.waiting_on ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><span className="sq" style={{ background: '#FCBB00' }} />{roleLabel(s.waiting_on)}</span> : '—'}{s.repeats != null && s.repeats > 1 && <span> · <span style={{ color: '#5a48c0' }}>repeats {s.repeats}× / wk</span></span>}</div></div>
                </div>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', padding: '10px 0 12px', borderTop: '1px solid rgba(0,0,0,0.08)', fontSize: 13, color: 'rgba(0,0,0,0.62)' }}>
              <span>{steps.length} of {steps.length} steps visible to the board</span>
              <span className="mono" style={{ marginLeft: 'auto', fontSize: 11, color: '#151515' }}>Day total · {hoursMinutes(total)}</span>
            </div>
          </div>

          <div className="p-proof">
            <div className="p-black">
              <ShieldCheck stroke="#34d399" />
              <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                <div style={{ fontSize: 14, fontWeight: 600, lineHeight: '20px' }}>Added to the Northwind Fitness board</div>
                <div style={{ fontSize: 13, lineHeight: '20px', color: 'rgba(255,255,255,0.74)', marginTop: 4 }}>Signed on the person’s machine. The team sees steps, times and hand-offs — never screens, messages or files.</div>
                <div className="mono" style={{ marginTop: 'auto', paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.16)', fontSize: 10, letterSpacing: '0.5px', color: 'rgba(255,255,255,0.7)' }}>Posted {hhmmss(r.approved_at)} · {steps.length} of {steps.length} steps visible to the board</div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
              <div>
                <div className="p-label" style={{ display: 'flex' }}><span>Record hash</span><span style={{ marginLeft: 'auto' }}>sha-256</span></div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid rgba(0,0,0,0.12)', borderRadius: 2, background: '#fff', padding: '4px 4px 4px 10px', marginTop: 6 }}>
                  <span className="mono" style={{ flex: 1, fontSize: 12, color: '#151515' }} title={r.hash}>{short(r.hash)}</span>
                  <button type="button" className="btn" style={{ height: 26, fontSize: 12, background: '#f8f8f6' }} onClick={() => { navigator.clipboard?.writeText(r.hash).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }}>{copied ? 'Copied' : 'Copy'}</button>
                </div>
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 30, borderBottom: '1px solid #151515', padding: '0 2px 4px' }}>
                  <svg width="120" height="24" viewBox="0 0 120 24" aria-hidden="true"><path d="M2 18 C 10 4, 16 4, 18 14 S 26 22, 30 10 S 40 2, 44 14 C 46 20, 52 20, 56 12 S 66 6, 70 14 S 82 18, 92 10 L 118 8" fill="none" stroke="#151515" strokeWidth="1.4" strokeLinecap="round" /></svg>
                  <span className="mono" style={{ marginLeft: 'auto', fontSize: 10, color: '#151515' }} title={r.sig}>sig {short(r.sig)}</span>
                  <span className="mono" style={{ fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: '#0b5f58', display: 'inline-flex', alignItems: 'center', gap: 4 }}><Check size={10} stroke="#0b5f58" />Verified</span>
                </div>
                <div className="mono" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 10, letterSpacing: '0.4px', color: 'rgba(0,0,0,0.58)' }}>Signed with the device key · ed25519 · {short(r.pubkey)}</div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 32px 16px', borderTop: '1px dashed rgba(0,0,0,0.22)', flexWrap: 'wrap' }}>
            {state === 'idle' && <button type="button" className="btn withdraw" onClick={() => setState('confirm')}>Withdraw</button>}
            {state === 'confirm' && <><button type="button" className="btn withdraw" onClick={withdraw}>Confirm withdraw</button><button type="button" className="btn" style={{ height: 36 }} onClick={() => setState('idle')}>Keep it</button></>}
            {state === 'busy' && <span className="mono-11">withdrawing…</span>}
            {(state === 'done' || state === 'error') && <span className={`confirm-line${state === 'error' ? ' err' : ''}`}>{msg}</span>}
            {state === 'idle' && <span style={{ fontSize: 12, lineHeight: '18px', color: 'rgba(0,0,0,0.62)' }}>Takes it off the board any time. The steps stay on the person’s machine.</span>}
            <button type="button" className="btn-primary" style={{ marginLeft: 'auto', height: 36 }} onClick={onClose}>Done</button>
          </div>
        </section>
        <svg width="100%" height="10" viewBox="0 0 840 10" preserveAspectRatio="none" aria-hidden="true" style={{ display: 'block' }}>
          <polygon points={Array.from({ length: 141 }, (_, i) => `${i * 6},${i % 2 ? 10 : 0}`).join(' ')} fill="#f8f8f6" />
        </svg>
      </div>
    </div>
  );
}

const TOOL_COLORS: Record<string, string> = { sheets: '#0F766E', slides: '#B45309', docs: '#3B73FF', mail: '#5e6875', meet: '#104e64', figma: '#6D5BD0', calendar: '#30373f' };
function ToolDot({ tool }: { tool: string }) {
  return <span title={tool} style={{ width: 16, height: 16, flex: '0 0 16px', borderRadius: 4, background: TOOL_COLORS[tool] ?? '#9aa1a6', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontFamily: 'var(--mono)', fontSize: 8, textTransform: 'uppercase' }}>{tool.slice(0, 1)}</span>;
}
