import { useModel } from '../lib/api';
import { dayTime, int } from '../lib/format';
import { AskWhy, Kicker, Loading, NextLink, SourceChip, StackedHeader, Stamp, Verdict } from '../components/Chrome';
import './pages.css';

const fmtVal = (v: number, unit: 'h' | '%' | '/day') => (unit === '%' ? `${Math.round(v)}%` : v.toFixed(1));
const fmtRange = (lo: number, hi: number, unit: 'h' | '%' | '/day') => (unit === '%' ? `(${Math.round(lo)}–${Math.round(hi)})` : `(${lo.toFixed(1)}–${hi.toFixed(1)})`);

export default function ModelPage() {
  const res = useModel();
  if (!res) return <main className="main tight"><Loading what="model check" /></main>;
  const d = res.data;
  const inRange = d.sim_checks.filter((s) => s.in_range).length;
  const allIn = inRange === d.sim_checks.length;
  const better = d.demand.filter((x) => x.verdict === 'better').length;
  const maxLift = Math.max(8, ...d.demand.flatMap((x) => [x.lift, x.population_lift, x.ci[1]]));
  const axisMax = Math.ceil(maxLift / 2) * 2;
  const w = (x: number) => `${((x / axisMax) * 100).toFixed(1)}%`;
  const axisTicks = Array.from({ length: axisMax / 2 + 1 }, (_, i) => i * 2);
  const headline = allIn
    ? "Flowline-1 predicts this company well enough to act on — and says where it can't."
    : `Flowline-1 missed ${d.sim_checks.length - inRange} of ${d.sim_checks.length} predictions — it says so, and stops suggesting those changes.`;

  return (
    <main className="main tight">
      <SourceChip source={d.source} />
      <StackedHeader
        crumbs={[{ label: 'Northwind Fitness' }, { label: 'Trust' }, { label: 'Model check' }]}
        stamp={<Stamp origin={res.origin} error={res.error} at={d.calibrated_at} />}
        title="Flowline-1 · model check"
        right={`Northwind · calibrated ${dayTime(d.calibrated_at)} · ${int(d.records)} approved records`}
      />

      <div>
        <Kicker>A model of how this company works · calibrated on its own records</Kicker>
        <div className="headline-row">
          <h1 className="headline" style={{ marginTop: 12 }}>{headline}</h1>
          <AskWhy source={d.source} lines={[
            `Calibrated ${dayTime(d.calibrated_at)} on ${int(d.records)} approved records`,
            `Team simulator: ${inRange} of ${d.sim_checks.length} predictions landed inside their ${d.sim_checks.length ? 'predicted range' : 'range'}`,
            `Demand model: ${better} of ${d.demand.length} industries beat picking by population in the ${d.d1 ? 'frozen-clock' : ''} backtest`,
            `D1 fit: ${d.d1.dataset}, fitted ${d.d1.fit_year}, tested ${d.d1.test_year} · median error ${Math.round(d.d1.median_error * 100)}%`,
          ]} />
        </div>
      </div>

      <section aria-label="What Flowline-1 is" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 24 }}>
        {d.components.map((p) => (
          <div key={p.n} style={{ borderTop: '1px solid #171717', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span className="mono-11">{p.n}</span><span style={{ fontSize: 16, fontWeight: 600 }}>{p.name}</span></div>
            <div style={{ fontSize: 13, lineHeight: '20px', color: 'var(--muted)' }}>{p.what}</div>
            <div className="mono" style={{ fontSize: 11, color: '#000' }}>{p.size}</div>
          </div>
        ))}
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 20 }}>
        <section aria-label="Team simulator: predicted vs measured" className="mc-card">
          <div className="head"><span style={{ fontSize: 15, fontWeight: 600 }}>Team simulator</span><span style={{ fontSize: 13, color: 'var(--muted)' }}>predicted before the change vs measured after</span><span className="mono-10" style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>{inRange} of {d.sim_checks.length} in range</span></div>
          <div className="body">
            <div className="table">
              <div className="sim-grid" style={{ height: 30, background: 'var(--muted-2)' }}>
                <span className="label" style={{ paddingLeft: 12 }}>Measure</span><span className="label right">Predicted</span><span className="label" style={{ paddingLeft: 14 }}>Range · actual</span><span className="label right">Actual</span><span className="label right" style={{ paddingRight: 12 }}>Verdict</span>
              </div>
              {d.sim_checks.map((s) => {
                const pad = (s.hi - s.lo) * 0.6, d0 = s.lo - pad, d1 = s.hi + pad;
                const at = (x: number) => `${(((x - d0) / (d1 - d0)) * 100).toFixed(1)}%`;
                const wd = `${(((s.hi - s.lo) / (d1 - d0)) * 100).toFixed(1)}%`;
                return (
                  <div key={s.measure} className="sim-grid" style={{ minHeight: 38, borderTop: '1px solid var(--muted-2)', fontSize: 13 }}>
                    <span style={{ padding: '8px 8px 8px 12px' }}>{s.measure}</span>
                    <span className="mono-12 right nowrap">{fmtVal(s.predicted, s.unit)} <span style={{ fontSize: 11, color: 'var(--muted)' }}>{fmtRange(s.lo, s.hi, s.unit)}</span></span>
                    <span style={{ position: 'relative', height: 18, margin: '0 4px 0 14px' }}>
                      <span style={{ position: 'absolute', left: 0, right: 0, top: 8.5, height: 1, background: 'var(--border)' }} />
                      <span style={{ position: 'absolute', left: at(s.lo), width: wd, top: 4, height: 10, background: 'rgba(59,115,255,0.16)', borderLeft: '1px solid #3B73FF', borderRight: '1px solid #3B73FF' }} />
                      <span style={{ position: 'absolute', left: at(s.predicted), top: 3, width: 1, height: 12, background: '#3B73FF' }} />
                      <span style={{ position: 'absolute', left: at(s.actual), top: 4.5, width: 9, height: 9, marginLeft: -4.5, borderRadius: '50%', background: s.in_range ? '#0F766E' : '#C24D32', boxShadow: '0 0 0 1.5px #fff' }} />
                    </span>
                    <span className="mono-12 right" style={{ fontWeight: 600 }}>{fmtVal(s.actual, s.unit)}</span>
                    <span className="right" style={{ paddingRight: 12 }}><span className={`chip ${s.in_range ? 'teal' : 'amber'}`} style={{ padding: '2px 6px', height: 'auto' }}>{s.in_range ? 'In range' : 'Out of range'}</span></span>
                  </div>
                );
              })}
            </div>
            <div style={{ marginTop: 'auto', paddingTop: 10, display: 'flex', alignItems: 'center', gap: 14, fontSize: 12, color: 'var(--muted)', flexWrap: 'wrap' }}>
              <span className="legend"><span style={{ width: 16, height: 8, background: 'rgba(59,115,255,0.16)', borderLeft: '1px solid #3B73FF', borderRight: '1px solid #3B73FF' }} />predicted range</span>
              <span className="legend"><span style={{ width: 8, height: 8, borderRadius: '50%', background: '#0F766E' }} />measured after</span>
              <span>Ranges are the spread over reruns with new luck.</span>
            </div>
          </div>
        </section>

        <section aria-label="Demand model: backtest on public data" className="mc-card">
          <div className="head"><span style={{ fontSize: 15, fontWeight: 600 }}>Demand model</span><span style={{ fontSize: 13, color: 'var(--muted)' }}>clock frozen, regions hidden, scored on what happened</span><span className="mono-10" style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>lift, 0–{axisMax}×</span></div>
          <div className="body">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {d.demand.map((x) => (
                <div key={x.naics}>
                  <div style={{ display: 'flex', alignItems: 'baseline', fontSize: 13, marginBottom: 4 }}>
                    <span style={{ fontWeight: 500 }}>{x.industry}</span><span className="mono-10" style={{ marginLeft: 8 }}>{x.naics}</span>
                    <span className="mono" style={{ marginLeft: 'auto', fontSize: 11, color: x.verdict === 'better' ? '#0F766E' : '#6b4a00' }}>{x.verdict === 'better' ? 'Better than population' : 'No better — said so'}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '78px minmax(0, 1fr) 40px', columnGap: 8, rowGap: 3, alignItems: 'center', fontSize: 11, color: 'var(--muted)' }}>
                    <span>Flowline-1</span>
                    <span style={{ height: 12, position: 'relative' }}>{axisTicks.map((t) => <span key={t} style={{ position: 'absolute', left: `${(t / axisMax) * 100}%`, top: 0, bottom: 0, width: 1, background: t === 0 ? 'var(--rule)' : 'var(--muted-2)' }} />)}<span style={{ position: 'absolute', left: 0, top: 2, height: 8, width: w(x.lift), background: '#171717' }} /></span>
                    <span className="mono right" style={{ color: '#000', fontWeight: 600 }}>{x.lift.toFixed(1)}×</span>
                    <span>Population</span>
                    <span style={{ height: 12, position: 'relative' }}>{axisTicks.map((t) => <span key={t} style={{ position: 'absolute', left: `${(t / axisMax) * 100}%`, top: 0, bottom: 0, width: 1, background: t === 0 ? 'var(--rule)' : 'var(--muted-2)' }} />)}<span style={{ position: 'absolute', left: 0, top: 2, height: 8, width: w(x.population_lift), background: '#B8BEC2' }} /></span>
                    <span className="mono right">{x.population_lift.toFixed(1)}×</span>
                  </div>
                </div>
              ))}
              <div style={{ display: 'grid', gridTemplateColumns: '78px minmax(0, 1fr) 40px', columnGap: 8 }}>
                <span /><div style={{ position: 'relative', height: 14, borderTop: '1px solid var(--muted-2)', paddingTop: 3 }}>{axisTicks.map((t, i) => <span key={t} className="mono-10" style={{ position: 'absolute', top: 3, left: `${(t / axisMax) * 100}%`, transform: `translateX(${i === 0 ? '0' : i === axisTicks.length - 1 ? '-100%' : '-50%'})` }}>{t}×</span>)}</div><span />
              </div>
            </div>
            <div style={{ marginTop: 'auto', paddingTop: 8, fontSize: 12, lineHeight: '18px', color: 'var(--muted)' }}>Lift = how much more often its top 10% of ZIP codes gained 3+ businesses than the average ZIP. US Census ZBP/CBP 2014–2023, ACS 2015–19.</div>
          </div>
        </section>
      </div>

      <div className="mono-11" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <span className="label">D1 fit</span>
        <span>{d.d1.dataset} · fitted {d.d1.fit_year}, tested {d.d1.test_year} · median error {Math.round(d.d1.median_error * 100)}%, p80 {Math.round(d.d1.p80_error * 100)}% · {int(d.d1.cases)} cases, {int(d.d1.events)} events{d.d1.amount_attr ? ' · amount attribute used' : ''}</span>
      </div>

      <section aria-label="What it can't call yet" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}><span style={{ fontSize: 16, fontWeight: 600, whiteSpace: 'nowrap' }}>What it can't call yet</span><span className="hair" /><span className="mono-10">{d.limits.length} limits · shown, not hidden</span></div>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(3, Math.max(1, d.limits.length))}, minmax(0, 1fr))`, gap: 16 }}>
          {d.limits.map((l) => (
            <div key={l.title} className="limit-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span className="sq s7" style={{ background: '#FCBB00' }} /><span style={{ fontSize: 14, fontWeight: 500 }}>{l.title}</span><span className="chip amber" style={{ marginLeft: 'auto', padding: '2px 6px', height: 'auto' }}>{l.tag}</span></div>
              <div style={{ fontSize: 12, lineHeight: '18px', color: 'var(--muted)' }}>{l.why}</div>
            </div>
          ))}
        </div>
      </section>

      <Verdict strong="Calibrated every night." rest="If a prediction leaves its range, the agent stops suggesting that change and tells you why.">
        <NextLink to="/improve/plans">Back to plans</NextLink>
      </Verdict>
    </main>
  );
}
