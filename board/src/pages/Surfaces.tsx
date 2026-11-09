// "One knowledge, many surfaces" hero (Surfaces.dc.html, §11). A fixed 1440×900 stage scaled to the viewport.
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useExpansion, useOntology, useRecordCount, useSurfaces } from '../lib/api';
import { int, longDate, hhmm, signed1 } from '../lib/format';
import { Loading, SourceChip } from '../components/Chrome';
import { HexMap } from '../components/HexMap';
import { Logo } from '../components/Icons';
import './Surfaces.css';

export default function SurfacesPage() {
  const s = useSurfaces();
  const o = useOntology();
  const x = useExpansion();
  const m = useRecordCount();
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const upd = () => setScale(Math.min(1, window.innerWidth / 1440));
    upd(); window.addEventListener('resize', upd); return () => window.removeEventListener('resize', upd);
  }, []);
  if (!s || !o || !x || m == null) return <main className="main"><Loading what="surfaces" /></main>;
  const d = s.data, ont = o.data, exp = x.data;
  const c = ont.counts;
  const lead = d.expansion_lead.slice().sort((a, b) => a.rank - b.rank);
  const predicted = (zip: string) => exp.zips.find((z) => z.zip === zip)?.predicted;
  const nodes = [
    { label: 'Roles', n: c.roles, color: '#6D5BD0', r: '50%', x: 140, y: 36 },
    { label: 'Steps', n: c.steps, color: '#171717', r: 2, x: 213, y: 58 },
    { label: 'Cases', n: c.cases, color: '#104e64', r: 3, x: 244, y: 112 },
    { label: 'Files', n: c.files, color: '#3B73FF', r: 3, x: 213, y: 166 },
    { label: 'Customers', n: c.customers, color: '#F99C00', r: '50%', x: 140, y: 188 },
    { label: 'Rules', n: c.rules, color: '#0F766E', r: 1, x: 67, y: 166 },
    { label: 'Branches', n: c.branches, color: '#30373f', r: 1, x: 36, y: 112 },
    { label: 'ZIP areas', n: c.zip_areas, color: '#88ACFA', r: 1, x: 67, y: 58 },
  ];
  const when = ont.recomputed_at;
  const industryName = exp.industries.find((i) => i.naics === exp.industry)?.name ?? '';

  return (
    <div className="sf-root" style={{ height: 900 * scale }}>
      <SourceChip source={d.source ?? ont.source} />
      <div className="sf-stage" style={{ transform: `scale(${scale})` }}>
        <div style={{ position: 'absolute', left: 72, top: 44, right: 72, display: 'flex', alignItems: 'flex-end', gap: 40 }}>
          <div style={{ flex: 1 }}>
            <div className="kicker"><span className="label">Northwind Fitness · 8 people · {c.branches} gyms · simulated</span><span className="hair" /></div>
            <h1 style={{ margin: '14px 0 0', fontSize: 40, fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15 }}>Eight people. One knowledge. Five different surfaces.</h1>
          </div>
          <p style={{ width: 380, fontSize: 15, lineHeight: '24px', color: 'var(--muted)' }}>Multiplayer isn’t everyone in one room. It’s everyone’s work in one knowledge — and nobody has to open a dashboard for it to work.</p>
        </div>

        <svg width="1440" height="900" viewBox="0 0 1440 900" style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }} aria-hidden="true">
          <g fill="none" stroke="#171717" strokeWidth="1.2">
            <path data-wire d="M268 410 H548 V448 H566" /><path data-wire d="M522 262 H544 V330 H566" /><path data-wire d="M546 520 H566" /><path data-wire d="M918 312 H898 V340 H874" /><path data-wire d="M918 590 H898 V530 H874" />
          </g>
          <g fill="#171717">{[[268, 410], [522, 262], [546, 520], [918, 312], [918, 590], [566, 448], [566, 330], [566, 520], [874, 340], [874, 530]].map(([cx, cy]) => <circle key={`${cx}${cy}`} cx={cx} cy={cy} r="3" />)}</g>
        </svg>

        <section aria-label="One knowledge" className="sf-knowledge">
          <div style={{ display: 'flex', alignItems: 'center' }}><span className="label" style={{ color: '#000' }}>One knowledge</span><span className="mono-10" style={{ marginLeft: 'auto' }}>v{ont.version} · {hhmm(when)}</span></div>
          <div style={{ position: 'relative', width: 280, height: 224, margin: '6px auto 0' }}>
            <svg width="280" height="224" viewBox="0 0 280 224" style={{ position: 'absolute', left: 0, top: 0 }} aria-hidden="true">{nodes.map((n) => <line key={n.label} x1="140" y1="112" x2={n.x} y2={n.y} stroke="#c4c9cc" strokeWidth="1" />)}</svg>
            {nodes.map((n) => (
              <div key={n.label} className="sf-node" style={{ left: n.x, top: n.y }}><span style={{ width: 10, height: 10, borderRadius: n.r, background: n.color }} />{n.label}<span className="mono-10">{int(n.n)}</span></div>
            ))}
            <div style={{ position: 'absolute', left: 140, top: 112, transform: 'translate(-50%, -50%)', background: '#171717', color: '#fff', padding: '7px 10px', borderRadius: 3, textAlign: 'center' }}>
              <div className="mono" style={{ fontSize: 8, letterSpacing: 1, color: 'rgba(255,255,255,0.6)' }}>FLOWLINE-1</div><div style={{ fontSize: 12, fontWeight: 600 }}>Northwind</div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 4 }}>
            <div><div className="num" style={{ fontSize: 20 }}>{int(m)}</div><div className="label-9">records</div></div>
            <div><div className="num" style={{ fontSize: 20 }}>{int(c.zip_areas)}</div><div className="label-9">ZIP areas</div></div>
            <div><div className="num" style={{ fontSize: 20 }}>0</div><div className="label-9">screens shared</div></div>
          </div>
        </section>

        {/* CEO phone */}
        <section data-surface aria-label="CEO: phone lock screen" className="sf-phone">
          <div className="sf-phone-screen">
            <span style={{ position: 'absolute', left: '50%', top: 9, transform: 'translateX(-50%)', width: 72, height: 20, borderRadius: 999, background: '#000' }} />
            <div style={{ position: 'absolute', left: 14, right: 14, top: 12, display: 'flex', fontSize: 10, fontWeight: 600 }}><span>07:40</span><span style={{ marginLeft: 'auto' }}>5G</span></div>
            <div style={{ textAlign: 'center', marginTop: 46, fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>{longDate(when)}</div>
            <div className="num" style={{ textAlign: 'center', fontSize: 54, letterSpacing: '-0.02em', lineHeight: 1.05 }}>7:40</div>
            <div style={{ position: 'absolute', left: 9, right: 9, top: 150, background: 'rgba(255,255,255,0.94)', color: '#000', borderRadius: 16, padding: '10px 11px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--muted)' }}><span style={{ width: 16, height: 16, borderRadius: 4, background: '#000', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}><Logo size={10} width={3} /></span>FLOWLINE<span style={{ marginLeft: 'auto' }}>now</span></div>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 6, lineHeight: 1.3 }}>Next club · {lead[0]?.zip ?? '—'}</div>
              <div style={{ fontSize: 11.5, lineHeight: 1.38, marginTop: 2, color: 'var(--ink-2)' }}>{d.ceo_line}</div>
            </div>
            <div style={{ position: 'absolute', left: 15, right: 15, top: 292, background: 'rgba(255,255,255,0.55)', color: '#000', borderRadius: 14, padding: '8px 10px', opacity: 0.85 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>CALENDAR · 08:00</div><div style={{ fontSize: 11, fontWeight: 600, marginTop: 2 }}>Ops sync · Club 2</div>
            </div>
            <span style={{ position: 'absolute', left: 22, bottom: 26, width: 34, height: 34, borderRadius: '50%', background: 'rgba(255,255,255,0.18)' }} />
            <span style={{ position: 'absolute', right: 22, bottom: 26, width: 34, height: 34, borderRadius: '50%', background: 'rgba(255,255,255,0.18)' }} />
            <span style={{ position: 'absolute', left: '50%', bottom: 8, transform: 'translateX(-50%)', width: 84, height: 4, borderRadius: 4, background: 'rgba(255,255,255,0.8)' }} />
          </div>
        </section>
        <Caption left={72} top={616} width={196} who="CEO" what="One line on the phone. No dashboard." tag="gets · one line" />

        {/* Trainer notch */}
        <section data-surface aria-label="Trainer: laptop notch" className="sf-laptop" style={{ left: 302, top: 196, width: 220, height: 132 }}>
          <div className="sf-laptop-screen">
            <div style={{ height: 10, background: 'rgba(255,255,255,0.7)' }} />
            <div className="sf-notch" style={{ width: 176 }}>
              <div className="mono" style={{ fontSize: 8, letterSpacing: 1, color: 'rgba(255,255,255,0.6)' }}>END OF DAY · 18:00</div>
              <div style={{ fontSize: 11.5, fontWeight: 600, marginTop: 3, lineHeight: 1.3 }}>Today’s work is ready to review</div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.72)', marginTop: 2 }}>{d.trainer_record.steps} steps · {d.trainer_record.left_out} personal left out</div>
              <div style={{ display: 'flex', gap: 5, marginTop: 7 }}><span className="sf-btn white">Review</span><span className="sf-btn ghost">Tomorrow</span></div>
            </div>
          </div>
        </section>
        <div style={{ position: 'absolute', left: 290, top: 328, width: 244, height: 8, background: '#2a2f36', borderRadius: '0 0 6px 6px' }} />
        <Caption left={302} top={336} width={220} who="Trainer" what="Nothing all day. Two minutes at 18:00." tag="gives · day record" />

        {/* Finance inbox */}
        <section data-surface aria-label="Finance: inbox" className="sf-inbox">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', borderBottom: '1px solid var(--muted-2)' }}><span className="sf-dot" /><span className="sf-dot" /><span className="mono" style={{ fontSize: 9, letterSpacing: 1, color: 'var(--muted)', marginLeft: 6 }}>INBOX · {d.finance_inbox.length}</span></div>
          {d.finance_inbox.map((it, i) => (
            i === 0 ? (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '9px 10px', background: '#fffcf5', boxShadow: 'inset 3px 0 0 #FCBB00' }}>
                <span style={{ width: 22, height: 22, flex: '0 0 22px', borderRadius: '50%', background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Logo size={12} width={3} /></span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', fontSize: 11 }}><strong>Flowline</strong><span style={{ marginLeft: 'auto', color: 'var(--muted)' }}>09:12</span></div>
                  <div style={{ fontSize: 11, fontWeight: 600, marginTop: 1 }}>{it.title}</div>
                  <div style={{ fontSize: 10.5, color: 'var(--muted)', lineHeight: 1.35 }}>{it.sub}</div>
                  {it.actions.length > 0 && <div style={{ display: 'flex', gap: 5, marginTop: 6 }}>{it.actions.map((a, j) => <span key={a} className={`sf-btn ${j === 0 ? 'black' : 'outline'}`}>{a}</span>)}</div>}
                </div>
              </div>
            ) : (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '8px 10px', borderTop: '1px solid var(--muted-2)', color: 'var(--muted)' }}>
                <span style={{ width: 22, height: 22, flex: '0 0 22px', borderRadius: '50%', background: 'var(--muted-2)', fontSize: 9, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{it.title.split(/[\s·]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()}</span>
                <div style={{ fontSize: 10.5, lineHeight: 1.35 }}><div>{it.title}</div><div style={{ color: 'var(--grey-text)' }}>{it.sub}</div></div>
              </div>
            )
          ))}
        </section>
        <Caption left={302} top={664} width={244} who="Finance" what="One approval, in their own inbox." tag={`gets · ${d.finance_inbox.filter((i) => i.actions.length).length} approval`} />

        {/* Expansion lead browser */}
        <section data-surface aria-label="Expansion lead: browser" className="sf-browser">
          <div style={{ height: 28, flex: '0 0 28px', display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px', borderBottom: '1px solid var(--muted-2)', background: '#f7f8f9' }}>
            <span className="sf-dot" /><span className="sf-dot" /><span className="sf-dot" />
            <span className="mono" style={{ marginLeft: 10, flex: 1, height: 16, borderRadius: 4, background: '#fff', border: '1px solid var(--muted-2)', fontSize: 9, color: 'var(--muted)', display: 'flex', alignItems: 'center', padding: '0 6px' }}>flowline.app/northwind/expand</span>
          </div>
          <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
            <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', inset: 0 }}><HexMap zips={exp.zips} city={exp.city} width={280} height={233} cols={14} showRanks={false} legendInside /></div>
            </div>
            <div style={{ width: 168, flex: '0 0 168px', borderLeft: '1px solid var(--muted-2)', padding: 10 }}>
              <div className="label" style={{ fontSize: 8.5 }}>Next location · {industryName.toLowerCase()}</div>
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', fontSize: 12 }}>
                {lead.map((l, i) => (
                  <div key={l.zip} style={{ display: 'flex', alignItems: 'center', padding: '7px 0', borderTop: i === 0 ? '1px solid #171717' : '1px solid var(--muted-2)' }}><span className="mono-10" style={{ width: 14 }}>{l.rank}</span><span style={{ fontWeight: i === 0 ? 600 : 400 }}>{l.zip}</span>{predicted(l.zip) != null && <span className="mono" style={{ marginLeft: 'auto', fontSize: 11 }}>{signed1(predicted(l.zip)!)}</span>}</div>
                ))}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 8, lineHeight: 1.4 }}>New {industryName.toLowerCase() === 'fitness' ? 'gyms' : 'sites'} expected by ZIP · recomputed nightly</div>
            </div>
          </div>
        </section>
        <Caption left={918} top={456} width={450} who="Expansion lead" what="The only person who needs a full screen." tag="sees · the ranking" link="/decide/expand" />

        {/* Branch manager notch */}
        <section data-surface aria-label="Branch manager: notch" className="sf-laptop wide" style={{ left: 918, top: 512, width: 450, height: 132, borderWidth: 9 }}>
          {/* the screen: menu-bar strip, camera housing, a document window below — so it reads as the top of a laptop */}
          <div style={{ height: 14, background: 'rgba(255,255,255,0.78)' }} />
          <div style={{ position: 'absolute', left: '50%', top: 0, transform: 'translateX(-50%)', width: 104, height: 14, background: '#000', borderRadius: '0 0 7px 7px' }} />
          <div style={{ position: 'absolute', left: 22, top: 34, right: 22, height: 120, background: '#fff', borderRadius: 6, border: '1px solid rgba(0,0,0,0.08)' }}>
            <div style={{ height: 14, borderBottom: '1px solid rgba(0,0,0,0.06)', display: 'flex', alignItems: 'center', gap: 4, padding: '0 8px' }}>
              <span style={{ width: 5, height: 5, borderRadius: 3, background: '#e5e7eb' }} /><span style={{ width: 5, height: 5, borderRadius: 3, background: '#e5e7eb' }} /><span style={{ width: 5, height: 5, borderRadius: 3, background: '#e5e7eb' }} />
            </div>
            <div style={{ margin: '10px 12px 0', width: '46%', height: 6, background: '#eceff1', borderRadius: 2 }} />
            <div style={{ margin: '6px 12px 0', width: '70%', height: 6, background: '#f1f3f4', borderRadius: 2 }} />
          </div>
          <div className="sf-notch" style={{ width: 368, top: 4, borderRadius: '0 0 14px 14px', padding: '12px 14px 11px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="mono" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 8, letterSpacing: 1, color: 'rgba(255,255,255,0.6)' }}><span className="sq s6" style={{ background: '#9d8cf0' }} />BLOCKER · CLUB 4 OPENING</div>
              <div style={{ fontSize: 12, fontWeight: 600, marginTop: 3, lineHeight: 1.3 }}>{d.branch_mgr_blocker.title}</div>
            </div>
            {d.branch_mgr_blocker.actions.map((a, i) => <span key={a} className={`sf-btn ${i === 0 ? 'white' : 'ghost'}`} style={{ height: 22, fontSize: 10.5 }}>{a}</span>)}
          </div>
        </section>
        <div style={{ position: 'absolute', left: 906, top: 644, width: 474, height: 8, background: '#2a2f36', borderRadius: '0 0 6px 6px' }} />
        <Caption left={918} top={650} width={450} who="Branch manager" what="Asked only when a blocker is theirs." tag="gets · blocker to clear" />

        <div style={{ position: 'absolute', left: 72, right: 72, top: 744, borderTop: '1px solid #171717', display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 32, paddingTop: 16 }}>
          <div><div className="label">Everyone gives</div><div style={{ fontSize: 15, lineHeight: '23px', marginTop: 6 }}>An approved record of how their day actually went. Nothing personal, nothing they didn’t see first.</div></div>
          <div><div className="label">Flowline-1 computes</div><div style={{ fontSize: 15, lineHeight: '23px', marginTop: 6 }}>The best next move — where to open, what to change — from your records plus what’s around each site. Every night.</div></div>
          <div><div className="label">Each person gets</div><div style={{ fontSize: 15, lineHeight: '23px', marginTop: 6 }}>Only the decision or task that is theirs, where they already are. The blocker clears; the plan moves.</div></div>
        </div>
        <Link to="/know/waits" className="mono-10 sf-back">open the board →</Link>
      </div>
    </div>
  );
}

function Caption({ left, top, width, who, what, tag, link }: { left: number; top: number; width: number; who: string; what: string; tag: string; link?: string }) {
  return (
    <div style={{ position: 'absolute', left, top, width }}>
      <div style={{ marginTop: 12 }}><div style={{ fontSize: 15, fontWeight: 600 }}>{who}</div><div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2, lineHeight: '18px' }}>{what}</div></div>
      <div className="label" style={{ marginTop: 6, color: '#5a48c0' }}>{link ? <Link to={link} style={{ color: 'inherit', textDecoration: 'none' }}>{tag}</Link> : tag}</div>
    </div>
  );
}
