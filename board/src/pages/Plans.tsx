import { useState } from 'react';
import { Link } from 'react-router-dom';
import { approvePlan, usePlans } from '../lib/api';
import { h1, niceTicks, pct, signedPct } from '../lib/format';
import { AskWhy, Kicker, Loading, DataStamp, PageHeader, SourceChip, Verdict } from '../components/Chrome';
import { ArrowRight, Check } from '../components/Icons';
import './pages.css';

const COLS = '26px minmax(0, 236px) minmax(0, 1fr) 56px 64px';

export default function PlansPage() {
  const res = usePlans();
  const [approved, setApproved] = useState<{ id: string; ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!res) return <main className="main"><Loading what="plans" /></main>;
  const d = res.data;
  // tolerate partial plan objects from a stub API: default what the design needs
  const plans = [...d.plans]
    .map((p, i) => ({
      ...p,
      rank: p.rank ?? i + 1, sub: p.sub ?? '', hours: p.hours ?? 0,
      work_h: p.work_h ?? p.hours ?? 0, waiting_h: p.waiting_h ?? 0,
      vs_today: p.vs_today ?? (d.today_h ? ((p.hours ?? 0) - d.today_h) / d.today_h : 0),
      best: p.best ?? false, today: p.today ?? false, held_best_n: p.held_best_n ?? 0,
      range_h: p.range_h ?? [p.hours ?? 0, p.hours ?? 0], who: p.who ?? [], rules: p.rules ?? [],
    }))
    .sort((a, b) => a.rank - b.rank);
  if (plans.length === 0) return <main className="main"><Loading what="plans (none returned)" /></main>;
  const best = plans.find((p) => p.best) ?? plans[0];
  const todayPlan = plans.find((p) => p.today);
  const max = Math.max(d.today_h || 0, ...plans.map((p) => p.hours)) || 1;
  const bestX = (best.hours / max) * 100;
  const ticks = niceTicks(0, max, 5).filter((v) => v <= max + 1e-9);
  const runnerUp = plans.find((p) => p.rank === best.rank + 1);

  async function onApprove() {
    setBusy(true);
    const r = await approvePlan(best.id);
    setBusy(false);
    if (r.ok) setApproved({ id: best.id, ok: true, msg: `Plan ${best.rank} approved. Each change goes only to ${best.who.filter((w) => !/nothing/i.test(w.change)).map((w) => `the ${w.role}`).join(' and ')}.` });
    else setApproved({ id: best.id, ok: false, msg: r.status === 0 ? 'API offline — nothing was sent. Start the API on 8787 and try again.' : `The API answered ${r.status}; nothing was changed.` });
  }

  return (
    <main className="main">
      <SourceChip source={d.source} />
      <PageHeader crumbs={[{ label: 'Northwind Fitness' }, { label: 'Client proposals', to: '/know/waits' }, { label: 'Plans to test' }]} stamp={<DataStamp res={res} data={d} />} />

      <div>
        <Kicker>{plans.length} plans · same team, same {d.weeks} weeks, same luck · {d.reruns} reruns</Kicker>
        <div className="headline-row">
          <h1 className="headline">{d.headline}</h1>
          <AskWhy source={d.source} lines={[
            `${plans.length} plans replayed on the same team, the same ${d.weeks} weeks of requests, the same luck`,
            `${d.reruns} reruns per plan with new luck; the best plan held in ${best.held_best_n} of ${d.reruns}`,
            `Today: ${h1(d.today_h)} per proposal · best plan: ${h1(best.hours)} (${best.range_h[0]}–${best.range_h[1]} across reruns)`,
          ]} />
        </div>
        <p className="sub">Every plan replays the same requests and meetings. Only the plan changes, so the gap is the plan.</p>
      </div>

      <div className="plans-grid">
        <section aria-label="Plans ranked">
          <div className="table">
            <div className="thead" style={{ gridTemplateColumns: COLS, columnGap: 14 }}>
              <span>#</span><span>Plan</span>
              <span style={{ display: 'flex', gap: 14 }}>
                <span className="legend" style={{ fontFamily: 'inherit', fontSize: 'inherit' }}><span className="sq" style={{ background: '#171717' }} />Work</span>
                <span className="legend" style={{ fontFamily: 'inherit', fontSize: 'inherit' }}><span className="sq" style={{ background: '#FCBB00' }} />Waiting</span>
                <span className="legend" style={{ fontFamily: 'inherit', fontSize: 'inherit' }}><span style={{ width: 0, height: 10, borderLeft: '1px dashed #0F766E' }} />Best</span>
              </span>
              <span className="right">Hours</span><span className="right">vs today</span>
            </div>
            {plans.map((p) => {
              const fg = p.best ? '#000' : '#30373f';
              return (
                <div key={p.id} data-plan-row className="trow plan-row" style={{ gridTemplateColumns: COLS, columnGap: 14, background: p.best ? '#f5f9f9' : p.today ? '#fafbfb' : '#fff', boxShadow: p.best ? 'inset 0 0 0 2px #171717' : 'none' }}>
                  <span className="mono-12" style={{ color: fg }}>{p.rank}</span>
                  <div style={{ minWidth: 0 }}>
                    <div className="plan-name" style={{ fontWeight: p.best ? 600 : 400, color: fg }}>
                      <span className="ellipsis" title={p.name}>{p.name}</span>
                      {p.best && <span className="chip black" style={{ height: 16, flex: '0 0 auto' }}>Best</span>}
                      {p.today && <span className="chip grey" style={{ height: 16, flex: '0 0 auto' }}>Today</span>}
                    </div>
                    <div className="plan-sub ellipsis">{p.sub}</div>
                  </div>
                  <div className="plan-bar">
                    <span className="best-line" style={{ left: `${bestX}%` }} />
                    <span className="bars">
                      <span style={{ width: `${(p.work_h / max) * 100}%`, background: p.best ? '#171717' : '#5e6875' }} />
                      <span style={{ width: `${(p.waiting_h / max) * 100}%`, background: p.best ? '#FCBB00' : '#f3d27a' }} />
                    </span>
                  </div>
                  <span className="num right" style={{ fontSize: 20, color: fg }}>{p.hours.toFixed(1)}</span>
                  <span className="mono-12 right" style={{ color: p.best ? '#0F766E' : '#4d5353', fontWeight: p.best ? 600 : 400 }}>{signedPct(p.vs_today)}</span>
                </div>
              );
            })}
            <div className="trow plan-foot" style={{ gridTemplateColumns: COLS, columnGap: 14 }}>
              <span /><span className="label" style={{ alignSelf: 'center' }}>Hours per proposal</span>
              <div style={{ position: 'relative' }}>
                {ticks.map((v) => {
                  const x = (v / max) * 100;
                  const last = v === ticks[ticks.length - 1];
                  return (
                    <span key={v} style={{ display: 'contents' }}>
                      <span className="tick" style={{ left: `${x}%` }} />
                      <span className="tick-label" style={{ left: `${x}%`, transform: `translateX(${v === 0 ? '0' : last ? '-100%' : '-50%'})` }}>{last ? `${v} h` : v}</span>
                    </span>
                  );
                })}
              </div>
              <span /><span />
            </div>
          </div>
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>Bars to scale: a full bar is today's {h1(d.today_h)}. Approval rules move waiting; the deck options move work.</div>
        </section>

        <section data-best-card aria-label="Recommended plan" className="best-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="chip black" style={{ height: 20, fontSize: 10, padding: '0 8px' }}>Best</span>
            <span className="mono-11">held in {best.held_best_n} of {d.reruns} reruns</span>
            <span className="mono-11" style={{ marginLeft: 'auto', color: '#0F766E', fontWeight: 600 }}>{signedPct(best.vs_today)} vs today</span>
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.35 }}>{best.name} {best.sub}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 16 }}>
            <div className="stat" style={{ paddingTop: 10 }}><span className="label">Hours</span><span className="v">{best.hours.toFixed(1)}</span><span className="s">{best.range_h[0]}–{best.range_h[1]} across reruns</span></div>
            <div className="stat" style={{ paddingTop: 10 }}><span className="label">Waiting</span><span className="v">{todayPlan ? `${Math.round(todayPlan.waiting_h)} → ${Math.round(best.waiting_h)} h` : `${best.waiting_h.toFixed(1)} h`}</span><span className="s">{pct(best.waiting_h / best.hours)} of the cycle</span></div>
          </div>
          <div>
            <div className="label" style={{ paddingBottom: 6, borderBottom: '1px solid var(--border)' }}>Who it touches</div>
            {best.who.map((w) => (
              <div key={w.role} className="who-row"><span style={{ fontWeight: 500 }}>{w.role}</span><span style={{ marginLeft: 'auto', color: 'var(--muted)' }}>{w.change}</span></div>
            ))}
          </div>
          {approved?.id === best.id && approved.ok ? (
            <div className="confirm-line" style={{ height: 44, justifyContent: 'center', border: '1px solid rgba(15,118,110,0.3)', borderRadius: 2, background: 'rgba(15,118,110,0.06)' }}><Check stroke="#0F766E" size={12} />approved</div>
          ) : (
            <button type="button" className="btn-primary" style={{ height: 44, justifyContent: 'center' }} onClick={onApprove} disabled={busy}>{busy ? 'Approving…' : 'Approve this plan'} <ArrowRight /></button>
          )}
          {approved?.id === best.id && <div className={`confirm-line${approved.ok ? '' : ' err'}`} style={{ lineHeight: '16px' }}>{approved.msg}</div>}
          <div style={{ fontSize: 12, lineHeight: '18px', color: 'var(--muted)' }}>{d.note}</div>
        </section>
      </div>

      <Verdict strong={`Plan ${best.rank} wins on the same team, with the same luck.`} rest={runnerUp ? `The next best plan is ${(runnerUp.hours - best.hours).toFixed(1)} h slower; nothing changes until you approve.` : 'Nothing changes until you approve.'}>
        <Link to="/know/waits" className="btn lg">Back to where work waits</Link>
      </Verdict>
    </main>
  );
}
