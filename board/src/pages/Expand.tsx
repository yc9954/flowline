import { useSearchParams } from 'react-router-dom';
import { useExpansion } from '../lib/api';
import { dayMon, int, signed1, signedInt } from '../lib/format';
import { industry as industryWords } from '../lib/industry';
import { AskWhy, BLink, Kicker, Loading, DataStamp, NextLink, SourceChip, StackedHeader, Stat, Verdict } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import { BUCKETS, HexMap } from '../components/HexMap';
import './pages.css';

export default function ExpandPage() {
  const [params] = useSearchParams();
  const industry = params.get('industry') ?? undefined;
  const res = useExpansion(industry);
  if (!res) return <main className="main tight"><Loading what="expansion" /></main>;
  if (res.kind !== 'data') return <NotReady res={res} crumbs={[{ label: 'Expansion' }, { label: 'Where to open next' }]} what="expansion" className="main tight" />;
  const d = res.data;
  const zips = [...d.zips].sort((a, b) => a.rank - b.rank);
  const top = zips.filter((z) => z.rank <= 5);
  const pick = zips.find((z) => z.pick) ?? zips[0];
  const scale = Math.max(6, Math.ceil(Math.max(...top.map((z) => Math.max(z.predicted, z.happened)))));
  const mean = zips.reduce((a, z) => a + z.predicted, 0) / (zips.length || 1);
  const sortedP = zips.map((z) => z.predicted).sort((a, b) => a - b);
  const median = sortedP.length ? sortedP[Math.floor(sortedP.length / 2)] : 0;
  const bt = d.backtest;
  const axisMax = Math.ceil(Math.max(8, ...bt.by_industry.flatMap((b) => [b.lift, b.population_lift, b.ci[1]])) / 2) * 2;
  const X = (v: number) => `${((v / axisMax) * 100).toFixed(2)}%`;
  const ties = bt.by_industry.filter((b) => b.verdict === 'tie');
  const cur = bt.by_industry.find((b) => b.naics === d.industry);
  const indName = d.industries.find((i) => i.naics === d.industry)?.name ?? d.industry;
  const words = industryWords(d.industry);
  const sitesWord = words.known ? words.sites : indName.toLowerCase();  // "gyms", "practices", "cafés"…
  const movedUp = Math.round((new Date(d.opening.was).getTime() - new Date(d.opening.date).getTime()) / 86400000);

  return (
    <main className="main tight">
      <SourceChip source={d.source} />
      <StackedHeader
        crumbs={[{ label: 'Expansion' }, { label: 'Where to open next' }]}
        stamp={<DataStamp res={res} data={d} />}
        title={`Where to open next · ${d.city}`}
        right={`${d.zips_considered} ZIPs · ${d.branches} branches · ${int(d.records)} records`}
      >
        {d.industries.map((i) => (
          <BLink key={i.naics} to={`/decide/expand?industry=${i.naics}`} className={`tab${i.naics === d.industry ? ' on' : ''}`} aria-pressed={i.naics === d.industry}>{i.name} · {i.naics}</BLink>
        ))}
      </StackedHeader>

      <div className="expand-head">
        <div style={{ flex: '999 1 520px', minWidth: 0 }}>
          <Kicker>Recommendation · {d.zips_considered} {d.city.split(',')[0]} ZIPs · your {d.branches} branches · {int(d.records)} approved records</Kicker>
          <div className="headline-row">
            <h1 className="headline" style={{ marginTop: 12, lineHeight: 1.25 }}>{d.headline}</h1>
            <AskWhy source={d.source} lines={[
              `${d.zips_considered} ${d.city} ZIPs scored for NAICS ${d.industry} (${indName}) from ${bt.frozen_at} public data; ranked by predicted net new businesses`,
              `Your ${d.branches} branches and ${int(d.records)} approved records add what wins locally`,
              `Backtest: clock frozen at ${bt.frozen_at}, scored on ${bt.scored_on} over ${int(bt.n_zips)} ZIPs — lift ${bt.lift}× (95% CI ${bt.ci[0]}–${bt.ci[1]})${cur ? ` vs ${cur.population_lift}× by population` : ''}`,
            ]} />
          </div>
          <p className="sub" style={{ fontSize: 16, lineHeight: '26px', marginTop: 10, maxWidth: 680 }}>{d.sub}</p>
        </div>
        <div style={{ flex: '1 1 300px', minWidth: 0, display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 20, alignContent: 'start' }}>
          <Stat label="Rank" value={`${pick.rank} of ${d.rank_of}`} sub={`${d.city.split(',')[0]} metro ZIPs`} style={{ padding: '12px 0' }} />
          <Stat label="Opening" value={dayMon(d.opening.date)} sub={`was ${dayMon(d.opening.was)} · ${d.opening.blockers_cleared} blockers cleared`} style={{ padding: '12px 0' }} />
        </div>
      </div>

      <div className="expand-grid">
        <section aria-label="Top ZIPs" className="zips-card">
          <div className="map-col">
            <div style={{ display: 'flex', alignItems: 'center' }}><span className="label">{d.city.split(',')[0]} metro</span><span className="mono-10" style={{ marginLeft: 'auto' }}>{d.zips_considered} ZIPs</span></div>
            <HexMap zips={d.zips} city={d.city} />
            <div>
              <div style={{ display: 'flex', gap: 2 }}>{BUCKETS.map((c) => <span key={c} style={{ flex: 1, height: 8, background: c }} />)}</div>
              <div className="mono" style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3, fontSize: 9, color: 'var(--muted)' }}><span>0</span><span>+1</span><span>+2</span><span>+3</span><span>+4</span></div>
              <div style={{ marginTop: 4, fontSize: 11, lineHeight: '15px', color: 'var(--muted)' }}>Predicted net new {sitesWord}, {bt.frozen_at} → {bt.scored_on}</div>
            </div>
            <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: 10, paddingTop: 8, borderTop: '1px solid var(--muted-2)', fontSize: 11, color: 'var(--muted)' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><span style={{ width: 12, height: 12, border: '2px solid #171717', background: '#3B73FF', borderRadius: 2 }} />pick</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><span className="mono" style={{ width: 11, height: 11, border: '1px solid #171717', borderRadius: '50%', fontSize: 7, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#000' }}>2</span>rank</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><span style={{ width: 14, height: 4, background: '#bcd0e6', borderRadius: 2 }} />water</span>
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <div className="label" style={{ display: 'grid', gridTemplateColumns: '30px minmax(0, 1fr) 64px 76px', alignItems: 'center', background: 'var(--muted-2)', height: 32 }}>
              <span style={{ paddingLeft: 12 }}>#</span><span>ZIP · why</span><span className="right">Predicted</span><span className="right" style={{ paddingRight: 12 }}>Happened</span>
            </div>
            {top.map((r, i) => (
              <div key={r.zip} data-zip-row className={`zip-row${i === 0 ? ' is-hot' : ''}`}>
                <span className="mono-12" style={{ paddingLeft: 12, color: i === 0 ? '#000' : 'var(--muted)' }}>{r.rank}</span>
                <div style={{ padding: '12px 8px 12px 0', minWidth: 0 }}>
                  <div className="ellipsis" style={{ fontSize: 14, fontWeight: i === 0 ? 600 : 500 }}>{r.zip} <span style={{ fontWeight: 400, color: 'var(--muted)' }}>{r.name}</span></div>
                  {r.why.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 5 }}>{r.why.slice(0, 2).map((w) => <span key={w} className="why-chip">{w}</span>)}</div>}
                </div>
                <div style={{ paddingLeft: 10 }}>
                  <div className="mono right" style={{ fontSize: 13 }}>{signed1(r.predicted)}</div>
                  <div style={{ height: 4, marginTop: 5, background: 'var(--muted-2)', position: 'relative' }}><span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, (Math.max(0, r.predicted) / scale) * 100).toFixed(1)}%`, background: '#171717' }} /></div>
                </div>
                <div style={{ padding: '0 12px' }}>
                  <div className="mono right" style={{ fontSize: 13, fontWeight: 600, color: '#0F766E' }}>{signedInt(r.happened)}</div>
                  <div style={{ height: 4, marginTop: 5, background: 'var(--muted-2)', position: 'relative' }}><span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, (Math.max(0, r.happened) / scale) * 100).toFixed(1)}%`, background: '#0F766E' }} /></div>
                </div>
              </div>
            ))}
            <div style={{ marginTop: 'auto', padding: '10px 12px', borderTop: '1px solid var(--border)', fontSize: 12, lineHeight: '18px', color: 'var(--muted)' }}>Net new businesses, predicted from {bt.frozen_at} conditions vs what happened by {bt.scored_on}. Bars on a 0–{scale} scale. Metro average {signed1(mean)}, median {median === 0 ? '0' : signed1(median)}.</div>
          </div>
        </section>

        <section aria-label="Checked against what really happened" className="backtest">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><span className="label" style={{ color: '#000' }}>Checked against what really happened</span><span className="mono-10" style={{ marginLeft: 'auto' }}>backtest · clock frozen at {bt.frozen_at}</span></div>
          <div style={{ fontSize: 15, lineHeight: '23px' }}>We froze the clock at {bt.frozen_at} and hid whole regions of the US from the model. In {int(bt.n_zips)} ZIPs with almost no {(cur?.name ?? indName).toLowerCase()}, its top 10% were:</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            <span data-lift-main className="num" style={{ fontSize: 44, lineHeight: 1, letterSpacing: '-0.03em' }}>{bt.lift.toFixed(1)}×</span>
            <span style={{ fontSize: 13, lineHeight: '18px', color: 'var(--muted)' }}>as likely to have 3+ by {bt.scored_on}{cur ? ` — vs ${cur.population_lift.toFixed(1)}× picking by population` : ''}<br /><span className="mono" style={{ fontSize: 11 }}>95% CI {bt.ci[0]}–{bt.ci[1]} · n = {int(bt.n_zips)} ZIPs</span></span>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 8, borderBottom: '1px solid var(--muted-2)' }}>
              <span className="label">Lift · top 10% of ZIPs</span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 12, height: 8, background: '#171717' }} />Flowline-1</span>
                <span className="legend" style={{ fontSize: 11 }}><span style={{ position: 'relative', width: 12, height: 8, display: 'inline-block' }}><span style={{ position: 'absolute', left: 0, right: 0, top: 3.5, height: 1, background: '#171717' }} /><span style={{ position: 'absolute', left: 0, top: 0, width: 1, height: 8, background: '#171717' }} /><span style={{ position: 'absolute', right: 0, top: 0, width: 1, height: 8, background: '#171717' }} /></span>95% CI</span>
                <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 2, height: 12, background: '#4d5353' }} />pick by population</span>
              </span>
            </div>
            {bt.by_industry.map((b) => (
              <div key={b.naics} className="lift-row">
                <div><div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div><div className="mono-10" style={{ marginTop: 2 }}>NAICS {b.naics}</div></div>
                <div style={{ position: 'relative', height: 24 }}>
                  {Array.from({ length: axisMax / 2 + 1 }, (_, i) => i * 2).map((t) => <span key={t} style={{ position: 'absolute', left: X(t), top: 0, bottom: 0, width: 1, background: t === 0 ? 'var(--rule)' : 'var(--muted-2)' }} />)}
                  <span style={{ position: 'absolute', left: 0, top: 7, height: 10, width: X(b.lift), background: '#171717' }} />
                  <span style={{ position: 'absolute', left: X(b.ci[0]), width: `calc(${X(b.lift)} - ${X(b.ci[0])})`, top: 11.5, height: 1, background: '#fff' }} />
                  <span style={{ position: 'absolute', left: X(b.ci[0]), top: 8, width: 1, height: 8, background: '#fff' }} />
                  <span style={{ position: 'absolute', left: X(b.lift), width: `calc(${X(b.ci[1])} - ${X(b.lift)})`, top: 11.5, height: 1, background: '#171717' }} />
                  <span style={{ position: 'absolute', left: X(b.ci[1]), top: 6, width: 1, height: 12, background: '#171717' }} />
                  <span style={{ position: 'absolute', left: `calc(${X(b.population_lift)} - 1px)`, top: 1, width: 2, height: 22, background: '#4d5353', boxShadow: '0 0 0 1px #fff' }} />
                </div>
                <div className="nowrap"><span className="mono-12" style={{ fontWeight: 600 }}>{b.lift.toFixed(1)}×</span> <span className="mono-11">vs {b.population_lift.toFixed(1)}×</span>{b.verdict === 'tie' && <span className="chip amber" style={{ padding: '2px 6px', height: 'auto', marginLeft: 4 }}>tie</span>}</div>
              </div>
            ))}
            <div style={{ display: 'grid', gridTemplateColumns: '118px minmax(0, 1fr) 118px', columnGap: 12, paddingTop: 4, borderTop: '1px solid var(--muted-2)' }}>
              <span /><div style={{ position: 'relative', height: 14 }}>{Array.from({ length: axisMax / 2 + 1 }, (_, i) => i * 2).map((t, i, arr) => <span key={t} className="mono-10" style={{ position: 'absolute', left: X(t), transform: `translateX(${i === 0 ? '0' : i === arr.length - 1 ? '-100%' : '-50%'})` }}>{t}×</span>)}</div><span className="mono-10">× more likely</span>
            </div>
          </div>
          <div style={{ fontSize: 12, lineHeight: '18px', color: 'var(--muted)', borderLeft: '2px solid var(--violet)', paddingLeft: 10 }}>
            {ties.length ? `For ${ties.map((t) => t.name.toLowerCase()).join(' and ')} the model only ties picking by population — we show that too. ` : 'Every industry here beats picking by population. '}
            All {bt.by_industry.length} industries together: {bt.pooled.lift.toFixed(1)}× vs {bt.pooled.population_lift.toFixed(1)}×.
          </div>
          <div className="mono-10" style={{ marginTop: 'auto' }}>Source: US Census ZIP &amp; County Business Patterns 2014–2023, ACS 2015–19</div>
        </section>
      </div>

      <Verdict strong="Recomputed every night." rest={`New public data, a new competitor, or a slower branch moves the ranking — and you hear about it only if the answer changes.${movedUp > 0 ? '' : ''}`}>
        <NextLink to="/decide/opening">See what blocks opening</NextLink>
      </Verdict>
    </main>
  );
}
