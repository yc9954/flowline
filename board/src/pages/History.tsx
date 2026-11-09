import { useHistory, useResults } from '../lib/api';
import { dayTime } from '../lib/format';
import { AskWhy, Kicker, Loading, DataStamp, NextLink, PageHeader, SourceChip, Verdict } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import { Check } from '../components/Icons';
import './pages.css';

const CRUMBS = [{ label: 'Improve' }, { label: 'Process history' }];

export default function HistoryPage() {
  const res = useHistory();
  const results = useResults();
  if (!res || !results) return <main className="main"><Loading what="history" /></main>;
  if (res.kind !== 'data') return <NotReady res={res} crumbs={CRUMBS} what="process history" />;
  const d = res.data;
  const measured = results.kind === 'data' ? results.data : null;  // Results only fills gaps in §7; the page stands without it
  const versions = [...d.versions].sort((a, b) => b.v - a.v);
  const baseline = versions.find((v) => v.status === 'baseline');
  const live = versions.filter((v) => v.status === 'live');
  // absolute hours: §7 baseline_h / now_h, else the baseline row's hours (v1 delta_h when it is absolute,
  // otherwise Results' first KPI "before"), and the measured cycle time now
  const kpiBefore = parseFloat(measured?.kpis[0]?.before ?? '');
  const baselineH = d.baseline_h ?? (baseline && baseline.delta_h > 0 ? baseline.delta_h : isNaN(kpiBefore) ? undefined : kpiBefore);
  const now = d.now_h ?? (measured?.measured ?? (baselineH != null ? baselineH + live.reduce((a, v) => a + v.delta_h, 0) : undefined));
  const pending = versions.find((v) => v.status === 'needs_yes');
  const changes = live.length;
  const words = ['zero', 'once', 'twice', 'three times', 'four times', 'five times', 'six times'];
  const doneSteps = d.loop.filter((s) => s.status === 'done');
  const ranFrom = doneSteps[0]?.at?.split('–')[0], ranTo = doneSteps[doneSteps.length - 1]?.at?.split('–').pop();
  const fmt = (h: number) => `${h < 0 ? '−' : ''}${Math.abs(h).toFixed(1)} h`;

  return (
    <main className="main">
      <SourceChip source={d.source} />
      <PageHeader crumbs={CRUMBS} stamp={<DataStamp res={res} data={d} />} />

      <div>
        <Kicker>Process history · {versions.length} versions</Kicker>
        <div className="headline-row">
          <h1 className="headline" style={{ marginTop: 12, lineHeight: 1.25 }}>{d.headline}</h1>
          <AskWhy source={d.source} lines={[
            `${versions.length} versions of the process; ${changes} changes live, ${pending ? '1 waiting for a yes' : 'none pending'}`,
            baseline && baselineH != null && now != null ? `${fmt(baselineH)} per case at v${baseline.v} · ${fmt(now)} now` : '',
            `Next loop run ${dayTime(d.next_run_at)}`,
          ].filter(Boolean)} />
        </div>
      </div>

      <section aria-label="The loop, tonight" className="loop-card">
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
          <span className="label">The loop · ran by itself tonight{ranFrom && ranTo ? `, ${ranFrom}–${ranTo}` : ''}</span>
          <span className="mono-11" style={{ marginLeft: 'auto' }}>next run {dayTime(d.next_run_at)}</span>
        </div>
        <ol className="loop">
          {d.loop.map((s, i) => {
            const done = s.status === 'done', nowS = s.status === 'now';
            const last = i === d.loop.length - 1;
            return (
              <li key={s.n} data-loop-step>
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  <span className="loop-dot" style={{ background: done ? '#171717' : nowS ? '#FCBB00' : '#fff', color: nowS ? '#000' : done ? '#fff' : '#4d5353', borderColor: done ? '#171717' : nowS ? '#e0a800' : '#c4c9cc', boxShadow: nowS ? '0 0 0 4px rgba(252,187,0,0.25)' : 'none' }}>
                    {done ? <Check /> : s.n}
                  </span>
                  <span style={{ flex: 1, marginLeft: 8, borderTop: last ? '0 solid transparent' : done ? '2px solid #171717' : '2px dashed #d8dddf' }} />
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 10 }}><span className="mono-10">{s.n}</span><span style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</span></div>
                <div className="mono" style={{ fontSize: 11, color: nowS ? '#6b4a00' : '#4d5353', marginTop: 3, height: 16, fontVariantNumeric: 'tabular-nums' }}>{s.at ?? '—'}</div>
                <div style={{ fontSize: 12, color: nowS ? '#6b4a00' : '#4d5353', marginTop: 2, lineHeight: 1.4 }}>{s.note}</div>
              </li>
            );
          })}
        </ol>
      </section>

      <div style={{ display: 'flex', gap: 28, alignItems: 'flex-start' }}>
        <section aria-label="Versions of the process" style={{ flex: '1 1 0', minWidth: 0 }}>
          <div className="sec-head"><h2>Versions</h2><span className="label">{baseline && baselineH != null && now != null ? `${fmt(baselineH)} at v${baseline.v} · ${fmt(now)} now` : `${versions.length} versions`}</span></div>
          <div className="table">
            {versions.map((v, i) => {
              const last = i === versions.length - 1;
              const S = v.status === 'needs_yes'
                ? { chipBg: '#f6ebd3', chipFg: '#6b4a00', bg: '#fffcf5', dot: '#FCBB00', ring: '#e0a800', ew: 600, chip: 'Needs your yes', effect: `predicted ${fmt(v.predicted_delta_h ?? 0)}` }
                : v.status === 'live'
                  ? { chipBg: 'rgba(15,118,110,0.1)', chipFg: '#0F766E', bg: '#fff', dot: '#0F766E', ring: '#0F766E', ew: 400, chip: 'Live', effect: fmt(v.delta_h) }
                  : { chipBg: '#edf0f2', chipFg: '#4d5353', bg: '#fff', dot: '#fff', ring: '#4d5353', ew: 400, chip: 'Baseline', effect: baselineH != null ? `${baselineH.toFixed(1)} h` : '—' };
              const solid = '2px solid #d8dddf', gap = '2px dashed #c4c9cc', none = '0 solid transparent';
              return (
                <div key={v.v} className="vrow" style={{ borderTop: i === 0 ? none : '1px solid #edf0f2', background: S.bg }}>
                  <div style={{ position: 'relative', alignSelf: 'stretch' }}>
                    <span style={{ position: 'absolute', left: 9, top: 0, height: 19, borderLeft: i === 0 ? none : last ? gap : solid }} />
                    <span style={{ position: 'absolute', left: 9, top: 19, bottom: 0, borderLeft: last ? none : i === versions.length - 2 ? gap : solid }} />
                    <span style={{ position: 'absolute', left: 4, top: 13, width: 12, height: 12, borderRadius: '50%', background: S.dot, border: `2px solid ${S.ring}`, boxShadow: `0 0 0 3px ${S.bg}` }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, padding: '11px 0' }}>
                    <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>v{v.v}</span>
                    <span className="mono-10">{v.when}</span>
                  </div>
                  <div style={{ minWidth: 0, padding: '11px 0' }}>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>{v.title}</div>
                    <div className="mono" style={{ fontSize: 10, letterSpacing: '0.3px', textTransform: 'uppercase', color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>{v.found}</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, padding: '11px 0' }}>
                    <span className="chip" style={{ background: S.chipBg, color: S.chipFg, padding: '0 7px' }}>{S.chip}</span>
                    <span className="mono-12" style={{ fontWeight: S.ew, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{S.effect}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section aria-label="What the agent learned from people" style={{ flex: '0 0 340px', minWidth: 0 }}>
          <div className="sec-head"><h2>Learned from people’s answers</h2><span className="label">{d.learned.length} rules changed</span></div>
          <div style={{ borderTop: '1px solid #171717' }}>
            {d.learned.map((l, i) => (
              <div key={i} style={{ padding: '11px 0', borderBottom: '1px solid var(--muted-2)' }}>
                <div style={{ fontSize: 13.5, lineHeight: '20px', fontWeight: 600 }}>{l.finding}</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 5, fontSize: 13, lineHeight: '19px', color: 'var(--muted)' }}><span className="mono" style={{ color: '#5a48c0' }} aria-hidden="true">→</span><span>{l.action}</span></div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {pending && now != null ? (
        <Verdict strong={`v${pending.v} is ready for your yes.`} rest={`${pending.title}, tested on the same team: ${fmt(now)} → ${fmt(now + (pending.predicted_delta_h ?? 0))} predicted.`}>
          <NextLink to="/improve/plans">Review v{pending.v}</NextLink>
        </Verdict>
      ) : (
        <Verdict strong={`The process changed ${words[changes] ?? `${changes} times`}.`} rest="Nothing is waiting for a yes tonight.">
          <NextLink to="/improve/plans">Plans to test</NextLink>
        </Verdict>
      )}
    </main>
  );
}
