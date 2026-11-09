import { Link } from 'react-router-dom';
import { useResults } from '../lib/api';
import { h1, niceTicks } from '../lib/format';
import { AskWhy, Kicker, Loading, DataStamp, NextLink, PageHeader, SourceChip, Verdict } from '../components/Chrome';
import './pages.css';

export default function ResultsPage() {
  const res = useResults();
  if (!res) return <main className="main"><Loading what="results" /></main>;
  const d = res.data;
  const before = d.series.filter((s) => !s.after), after = d.series.filter((s) => s.after);
  const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  const avgBefore = mean(before.map((s) => s.value));
  const avgAfter = mean(after.map((s) => s.value));
  const weeks = Array.from(new Set(d.series.map((s) => s.week))).sort((a, b) => a - b);
  const nW = weeks.length || 1;
  const vals = d.series.map((s) => s.value).concat([d.predicted.lo, d.predicted.hi]);
  const yTicksAsc = niceTicks(Math.min(...vals) - 2, Math.max(...vals) + 2, 5);
  const lo = yTicksAsc[0], hi = yTicksAsc[yTicksAsc.length - 1];
  const y = (v: number) => ((hi - v) / (hi - lo)) * 100;
  const yTicks = [...yTicksAsc].reverse();
  const firstAfterWeek = after.length ? Math.min(...after.map((s) => s.week)) : weeks[weeks.length - 1] + 1;
  const splitX = ((weeks.indexOf(firstAfterWeek) < 0 ? nW : weeks.indexOf(firstAfterWeek)) / nW) * 100;
  const dots = weeks.flatMap((w) => {
    const pts = d.series.filter((s) => s.week === w);
    const wi = weeks.indexOf(w);
    return pts.map((s, i) => ({ x: ((wi + (i + 0.5) / pts.length) / nW) * 100, y: y(s.value), after: s.after }));
  });
  const words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six'];
  const wa = d.weeks_after;

  return (
    <main className="main">
      <SourceChip source={d.source} />
      <PageHeader crumbs={[{ label: 'Northwind Fitness' }, { label: 'Client proposals', to: '/know/waits' }, { label: 'Results' }]} stamp={<DataStamp res={res} data={d} />} />

      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Kicker>Result · {wa != null ? `${words[wa] ?? wa} week${wa === 1 ? '' : 's'} after the change` : 'after the change'}</Kicker>
          <div className="headline-row">
            <h1 className="headline" style={{ fontSize: 38 }}>{d.headline}</h1>
            <AskWhy source={d.source} lines={[
              `${d.records} approved records · ${d.people} people · ${d.weeks} weeks (${before.length} proposals before the change, ${after.length} after)`,
              `Predicted ${h1(d.predicted.mid)} (${d.predicted.lo}–${d.predicted.hi}) · measured ${h1(d.measured)}`,
              `Change: ${d.change}`,
            ]} />
          </div>
          <p className="sub" style={{ fontSize: 16, lineHeight: '27px', marginTop: 12, maxWidth: 600 }}>{d.sub}</p>
          <div className="evidence">
            <span>Evidence</span><strong>{d.records} approved records · {d.people} people · {d.weeks} weeks</strong>
            <span>Change</span><strong>{d.change}</strong>
          </div>
        </div>

        <section aria-label="Cycle time per proposal, before and after the change" className="chart-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="label">Hours per proposal</span>
            <span className="legend" style={{ marginLeft: 'auto' }}><span className="sq" style={{ background: '#B8BEC2' }} />Before</span>
            <span className="legend"><span className="sq" style={{ background: '#0F766E' }} />After</span>
            <span className="legend"><span style={{ width: 12, height: 8, background: 'rgba(15,118,110,0.16)' }} />Predicted</span>
          </div>
          <div className="chart-grid">
            <div style={{ position: 'relative', height: 224 }}>
              {yTicks.map((v, i) => <span key={v} className="mono-10 y-tick" style={{ top: `${y(v)}%` }}>{i === 0 ? `${v} h` : v}</span>)}
            </div>
            <div className="plot">
              {yTicks.map((v) => <span key={v} className="gridline" style={{ top: `${y(v)}%` }} />)}
              {weeks.slice(1).map((w, i) => <span key={w} style={{ position: 'absolute', left: `${((i + 1) / nW) * 100}%`, top: 0, bottom: 0, borderLeft: '1px solid #f2f5f6' }} />)}
              <span style={{ position: 'absolute', left: `${splitX}%`, right: 0, top: `${y(d.predicted.hi)}%`, height: `${y(d.predicted.lo) - y(d.predicted.hi)}%`, background: 'rgba(15,118,110,0.16)' }} />
              <span style={{ position: 'absolute', left: 0, width: `${splitX}%`, top: `${y(avgBefore)}%`, borderTop: '1.5px solid #4d5353' }} />
              <span style={{ position: 'absolute', left: `${splitX}%`, right: 0, top: `${y(avgBefore)}%`, borderTop: '1px dashed #9aa1a6' }} />
              {after.length > 0 && <span style={{ position: 'absolute', left: `${splitX}%`, right: 0, top: `${y(avgAfter)}%`, borderTop: '1.5px solid #0F766E' }} />}
              {dots.map((p, i) => <span key={i} {...(p.after ? { 'data-dot-after': '' } : { 'data-dot-before': '' })} className="dot" style={{ left: `${p.x}%`, top: `${p.y}%`, background: p.after ? '#0F766E' : '#B8BEC2' }} />)}
              <span style={{ position: 'absolute', left: `${splitX}%`, top: -6, bottom: 0, borderLeft: '1px dashed #171717' }} />
              <span className="change-tag" style={{ left: `calc(${splitX}% + 6px)` }}>Change applied · W{firstAfterWeek} Mon</span>
            </div>
            <div style={{ position: 'relative', height: 224 }}>
              <span className="mono-10" style={{ position: 'absolute', left: 8, top: `${y(avgBefore)}%`, transform: 'translateY(-50%)', color: '#30373f', whiteSpace: 'nowrap' }}>avg {avgBefore.toFixed(1)} h</span>
              {after.length > 0 && <>
                <span className="mono-10" style={{ position: 'absolute', left: 8, top: `${y(avgAfter)}%`, transform: 'translateY(-50%)', fontWeight: 600, color: '#0F766E', whiteSpace: 'nowrap' }}>avg {avgAfter.toFixed(1)} h</span>
                <span className="mono" style={{ position: 'absolute', left: 8, top: `calc(${y(avgAfter)}% + 12px)`, fontSize: 9, color: '#0F766E', whiteSpace: 'nowrap', lineHeight: 1.3 }}>pred. {d.predicted.lo}–{d.predicted.hi}</span>
              </>}
            </div>
            <span />
            <div className="mono-10" style={{ display: 'grid', gridTemplateColumns: `repeat(${nW}, minmax(0, 1fr))`, paddingTop: 5, textAlign: 'center' }}>{weeks.map((w) => <span key={w}>W{w}</span>)}</div>
            <span className="mono-10" style={{ padding: '5px 0 0 8px' }}>week</span>
          </div>
        </section>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 24 }}>
        {d.kpis.map((t, ti) => (
          <article key={t.label} className="stat">
            <span className="label">{t.label}</span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              {t.before && <span className="num" style={{ fontSize: 18, color: 'var(--muted)', textDecoration: 'line-through' }}>{t.before}</span>}
              <span {...(ti === 0 ? { 'data-kpi-main': '' } : {})} className="num" style={{ fontSize: 30, lineHeight: 1, letterSpacing: '-0.02em' }}>{t.after}</span>
            </div>
            <span className="s">{t.sub}</span>
          </article>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 32, alignItems: 'flex-start' }}>
        <section aria-label="Who it touched" style={{ flex: '1 1 0', minWidth: 0 }}>
          <div className="sec-head"><h2>Who it touched</h2><span className="label">{d.who.length} roles · measured, not surveyed</span></div>
          <div className="table">
            <div className="thead" style={{ gridTemplateColumns: '96px minmax(0, 1fr) minmax(150px, max-content)', columnGap: 12 }}><span>Role</span><span>What changed</span><span className="right">Before → after</span></div>
            {d.who.map((w, i) => (
              <div key={w.role} className="trow" style={{ gridTemplateColumns: '96px minmax(0, 1fr) minmax(150px, max-content)', columnGap: 12, height: 38, background: i % 2 === 1 ? '#f5f7f8' : '#fff' }}>
                <span style={{ fontSize: 14, fontWeight: 500 }}>{w.role}</span><span className="ellipsis" style={{ fontSize: 14 }}>{w.what}</span><span className="mono-12 right nowrap">{w.before} → {w.after}</span>
              </div>
            ))}
          </div>
        </section>
        <section aria-label="Next constraint" style={{ flex: '0 0 380px', minWidth: 0 }}>
          <div className="sec-head"><h2>Next constraint</h2><span className="label">Found tonight</span></div>
          <div className="next-card">
            <div style={{ fontSize: 16, lineHeight: '25px' }}>
              {(() => { const i = d.next_constraint.headline.indexOf(' — '); return i > 0 ? <><strong>{d.next_constraint.headline.slice(0, i)}</strong>{d.next_constraint.headline.slice(i)}</> : <strong>{d.next_constraint.headline}</strong>; })()}
            </div>
            <div style={{ fontSize: 13, lineHeight: '20px', color: 'var(--muted)', marginTop: 6 }}>{d.next_constraint.sub}</div>
            <span className={`chip ${d.next_constraint.ready ? 'amber' : 'grey'}`} style={{ height: 20, fontSize: 10, padding: '0 8px', marginTop: 10 }}>{d.next_constraint.ready ? 'Ready to test' : 'Not yet testable'}</span>
          </div>
        </section>
      </div>

      <Verdict strong="The loop starts again." rest="Keep this change, then test plans for the next constraint.">
        <Link to="/improve/history" className="btn lg">Keep this change</Link>
        <NextLink to="/know/waits">Test the next constraint</NextLink>
      </Verdict>
    </main>
  );
}
