import { useFinding } from '../lib/api';
import { h1, pct, roleLabel } from '../lib/format';
import { capitalize } from '../lib/industry';
import { AskWhy, Kicker, Loading, DataStamp, NextLink, PageHeader, SourceChip, Stat, Verdict } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import './pages.css';

export default function WaitsPage() {
  const res = useFinding();
  if (!res) return <main className="main"><Loading what="finding" /></main>;
  if (res.kind !== 'data') return <NotReady res={res} crumbs={[{ label: 'Know' }, { label: 'Where work waits' }]} what="finding" />;
  const d = res.data;
  const total = d.kpis.cycle_time_h;
  const map = d.map;
  const first = map[0], last = map[map.length - 1];
  const selected = map.find((s) => s.selected);
  const longest = map.find((s) => s.longest_wait);
  const longestNext = longest ? map[map.indexOf(longest) + 1] : undefined;
  const waitOwner = (selected ?? longestNext)?.role;

  // to-scale track: hands-on then wait, in order
  type Seg = { w: number; kind: 'hands' | 'wait'; label: string; bold?: boolean };
  const segs: Seg[] = [];
  let selectedAt = 0, acc = 0;
  map.forEach((s) => {
    if (s.selected) selectedAt = acc;
    segs.push({ w: s.hands_on_h, kind: 'hands', label: s.hands_on_h >= 3 ? `${s.name} ${s.hands_on_h.toFixed(1)}` : '' });
    acc += s.hands_on_h;
    if (s.wait_after_h) {
      const nxt = map[map.indexOf(s) + 1];
      const owner = s.longest_wait ? (waitOwner ?? nxt?.role) : nxt?.role;
      segs.push({ w: s.wait_after_h, kind: 'wait', bold: !!s.longest_wait, label: s.longest_wait ? `Waiting for the ${owner ? roleLabel(owner) : 'next step'} · ${s.wait_after_h.toFixed(1)} h` : s.wait_after_h >= 1.5 ? s.wait_after_h.toFixed(1) : '' });
      acc += s.wait_after_h;
    }
  });
  const ticks = Array.from({ length: Math.floor(total / 10) + 1 }, (_, i) => i * 10);

  return (
    <main className="main">
      <SourceChip source={d.source} />
      <PageHeader crumbs={[{ label: capitalize(d.process) }, { label: 'Where work waits' }]} stamp={<DataStamp res={res} data={d} />} />

      <div style={{ display: 'flex', gap: 40, alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Kicker>Finding · {d.records} approved records · {d.people} people · {d.weeks} weeks</Kicker>
          <div className="headline-row">
            <h1 className="headline" style={{ fontSize: 36 }}>{d.headline}</h1>
            <AskWhy source={d.source} lines={[
              `${d.records} approved records from ${d.people} people over ${d.weeks} weeks`,
              `${d.process}: ${h1(d.kpis.cycle_time_h)} brief → sent, ${pct(d.kpis.waiting_share)} of it waiting`,
              longest ? `Longest wait: ${h1(longest.wait_after_h ?? 0)} after ${longest.name} (${longest.role}), before ${longestNext?.name ?? ''} (${longestNext?.role ?? ''})` : '',
            ].filter(Boolean)} />
          </div>
          <p className="sub" style={{ fontSize: 16, lineHeight: '26px', marginTop: 10, maxWidth: 640 }}>{d.sub}</p>
        </div>
        <div className="kpi-grid">
          <Stat attrs={{ 'data-kpi': '' }} label="Cycle time" value={h1(d.kpis.cycle_time_h)} sub={`${first.name.toLowerCase()} → ${last.name.toLowerCase()}`} />
          <Stat attrs={{ 'data-kpi': '' }} label="Waiting" value={pct(d.kpis.waiting_share)} sub="of each cycle" />
          <Stat soft attrs={{ 'data-kpi': '' }} label="Small cases" value={pct(d.kpis.small_quotes_share)} sub={`${pct(d.kpis.small_quotes_unchanged)} approved unchanged`} />
          <Stat soft attrs={{ 'data-kpi': '' }} label="Repeated by hand" value={`${d.kpis.repeated_by_hand_h_per_wk.toFixed(0)} h / wk`} sub={d.repeated[0] ? `${d.repeated[0].task.toLowerCase().replace(/^copy /, '')}` : ''} />
        </div>
      </div>

      <section aria-label="Process map" className="pmap">
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12 }}>
          <span className="label">Process map · built from records, not interviews</span>
          <span className="legend" style={{ marginLeft: 'auto' }}><span className="sq" style={{ background: '#171717' }} />Stage span</span>
          <span className="legend"><span className="sq" style={{ background: '#FCBB00' }} />Hand-off wait</span>
          <span className="mono-11">avg per case · {d.records} records</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'stretch' }}>
          {map.map((s, i) => {
            const prev = map[i - 1];
            const wait = prev?.wait_after_h && prev.wait_after_h > 0 ? prev.wait_after_h : undefined;
            const big = !!prev?.longest_wait;
            return (
              <div key={s.name} style={{ display: 'contents' }}>
                {wait != null && (
                  <div className="pmap-wait" style={{ flex: `0 0 ${big ? 112 : 64}px` }}>
                    <span className="mono" style={{ fontSize: 11, fontWeight: big ? 600 : 400, background: big ? '#FCBB00' : 'transparent', padding: '2px 6px', borderRadius: 2 }}>{h1(wait)}</span>
                    <span style={{ display: 'flex', alignItems: 'center', width: '100%' }}><span style={{ flex: 1, height: big ? 6 : 2, background: '#FCBB00' }} /><svg width="7" height="10" viewBox="0 0 7 10" aria-hidden="true"><path d="M0 0l7 5-7 5z" fill="#FCBB00" /></svg></span>
                    <span className="label-9">{big ? 'longest wait' : 'wait'}</span>
                  </div>
                )}
                <div className="pmap-step" style={{ borderColor: s.selected ? '#171717' : 'var(--border)', boxShadow: s.selected ? '0 0 0 1px #171717' : 'none' }}>
                  <div className="label ellipsis">{s.role}</div>
                  <div style={{ fontSize: 15, fontWeight: 600, marginTop: 3 }}>{s.name}</div>
                  <div className="mono-12" style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}><span className="sq" style={{ background: '#171717' }} />{h1(s.hands_on_h)}</div>
                  <div className="ellipsis" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 3 }}>{s.artifact}</div>
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid var(--muted-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="label">To scale · one case, {first.name.toLowerCase()} → {last.name.toLowerCase()} · stage spans include nights</span>
            <span className="mono-11" style={{ marginLeft: 'auto' }}>{h1(d.to_scale.hands_on_h)} in stages · {h1(d.to_scale.waiting_h)} waiting between stages</span>
          </div>
          <div style={{ position: 'relative', marginTop: 18 }}>
            {selected && (
              <>
                <span className="mono-10" style={{ position: 'absolute', left: `${(selectedAt / total) * 100}%`, bottom: '100%', marginBottom: 2, transform: 'translateX(-50%)', color: '#000', whiteSpace: 'nowrap' }}>{selected.artifact} {h1(selected.hands_on_h)}</span>
                <span style={{ position: 'absolute', left: `${(selectedAt / total) * 100}%`, top: -2, bottom: -2, borderLeft: '1px solid #171717', zIndex: 2 }} />
              </>
            )}
            <div className="track">
              {segs.map((t, i) => (
                <span key={i} {...(t.bold ? { 'data-wait-bar': '' } : {})} style={{ width: `${(t.w / total) * 100}%`, flex: '0 0 auto', background: t.kind === 'wait' ? '#FCBB00' : '#171717', color: t.kind === 'wait' ? '#000' : '#fff', fontWeight: t.bold ? 600 : 400 }}>{t.label}</span>
              ))}
            </div>
            <div className="track-axis">
              {ticks.map((v) => {
                const x = (v / total) * 100; const last = v === ticks[ticks.length - 1];
                return <span key={v} style={{ display: 'contents' }}><span className="tick" style={{ left: `${x}%` }} /><span className="tick-label" style={{ left: `${x}%`, top: 5, transform: `translateX(${v === 0 ? '0' : last ? '-100%' : '-50%'})` }}>{last ? `${v} h` : v}</span></span>;
              })}
            </div>
          </div>
        </div>
      </section>

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        <section aria-label="Sent back" style={{ flex: '1 1 0', minWidth: 0 }}>
          <div className="sec-head"><h2>Sent back</h2><span className="label">Rework loops · share of cases</span></div>
          <div className="table">
            <div className="thead" style={{ gridTemplateColumns: 'minmax(0, 1fr) 84px 92px 128px', columnGap: 12 }}><span>Reason</span><span>Back to</span><span className="right">Cost each</span><span className="right">Share</span></div>
            {d.sent_back.map((o, i) => (
              <div key={o.reason} className="trow" style={{ gridTemplateColumns: 'minmax(0, 1fr) 84px 92px 128px', columnGap: 12, height: 36, background: i === 0 ? '#f5f7f8' : '#fff' }}>
                <span className="ellipsis" style={{ fontSize: 14 }}>{o.reason}{o.by && <span style={{ fontSize: 12, color: 'var(--muted)' }}> · {o.by === 'Client' ? 'client asks' : o.by}</span>}</span>
                <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>{o.back_to}</span>
                <span className="mono-12 right">{o.cost}</span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'flex-end' }}><span style={{ width: 72, height: 6, background: 'var(--muted-2)', display: 'flex' }}><span style={{ width: `${o.share * 100}%`, background: '#C24D32' }} /></span><span className="mono-12" style={{ width: 32, textAlign: 'right' }}>{pct(o.share)}</span></span>
              </div>
            ))}
          </div>
        </section>
        <section aria-label="Repeated by hand" style={{ flex: '1 1 0', minWidth: 0 }}>
          <div className="sec-head"><h2>Repeated by hand</h2><span className="label">Per week · from records</span></div>
          <div className="table">
            <div className="thead" style={{ gridTemplateColumns: 'minmax(0, 1fr) 52px 88px 104px', columnGap: 12 }}><span>Task</span><span>Who</span><span className="right">Count · time</span><span>Owner next</span></div>
            {d.repeated.map((r) => (
              <div key={r.task} className="trow" style={{ gridTemplateColumns: 'minmax(0, 1fr) 52px 88px 104px', columnGap: 12, height: 36 }}>
                <span className="ellipsis" style={{ fontSize: 14 }}>{r.task}</span>
                <span style={{ fontSize: 13, color: 'var(--ink-2)' }}>{r.who}</span>
                <span className="mono-12 right">{r.count_per_wk}× · {r.minutes} m</span>
                <span style={{ display: 'flex' }}>{r.agent_can_do ? <span className="chip violet">Agent can do</span> : <span className="mono-11">—</span>}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <Verdict strong={waitOwner ? `The constraint is the ${roleLabel(waitOwner)}'s approval, not effort.` : 'The constraint is waiting, not effort.'} rest="Test plans on the same team before anything changes.">
        <NextLink to="/improve/plans">Next: Plans to test</NextLink>
      </Verdict>
    </main>
  );
}
