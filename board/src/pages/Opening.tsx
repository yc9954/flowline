import { useOpening } from '../lib/api';
import { dayMon, daysBetween, isoWeek, parseDate, roleColor, roleLabel, roleShort, wdDayMon, weekday } from '../lib/format';
import { AskWhy, Kicker, Loading, DataStamp, NextLink, SourceChip, StackedHeader, Verdict } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import { AgentBadge, DigestIcon, InboxIcon, NotchIcon } from '../components/Icons';
import './pages.css';

const LEFT = 272;

export default function OpeningPage() {
  const res = useOpening();
  if (!res) return <main className="main tight"><Loading what="opening" /></main>;
  if (res.kind !== 'data') return <NotReady res={res} crumbs={[{ label: 'Expansion', to: '/decide/expand' }, { label: 'Opening branch' }]} what="opening" className="main tight" />;
  const d = res.data;

  // timeline: from the Monday of the earliest start to the end of the week holding the latest end/opening
  const starts = d.workstreams.map((w) => parseDate(w.start).getTime());
  const ends = d.workstreams.map((w) => parseDate(w.end).getTime()).concat([parseDate(d.opens).getTime(), parseDate(d.was).getTime()]);
  const t0d = new Date(Math.min(...starts));
  const dow = (t0d.getUTCDay() + 6) % 7; // Monday = 0
  t0d.setUTCDate(t0d.getUTCDate() - dow);
  const t1d = new Date(Math.max(...ends));
  const nWeeks = Math.max(1, Math.ceil((t1d.getTime() - t0d.getTime()) / (7 * 86400000)));
  const span = nWeeks * 7;
  const iso = (dt: Date) => `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, '0')}-${String(dt.getUTCDate()).padStart(2, '0')}`;
  const t0 = iso(t0d);
  const x = (date: string) => `${((daysBetween(t0, date) / span) * 100).toFixed(3)}%`;
  const todayPct = daysBetween(t0, d.today) / span;
  const opensPct = daysBetween(t0, d.opens) / span;
  const weeks = Array.from({ length: nWeeks }, (_, i) => { const dt = new Date(t0d); dt.setUTCDate(dt.getUTCDate() + i * 7); return dt; });
  const movedUp = daysBetween(d.opens, d.was);
  const cleared = d.blockers.filter((b) => b.status === 'cleared').length;
  const ws = d.workstreams;

  const barColor = (s: typeof ws[number]['status']) => (s === 'done' ? '#0F766E' : s === 'waiting' ? '#FCBB00' : '#171717');
  const capColor = (s: typeof ws[number]['status']) => (s === 'done' ? '#0a524c' : s === 'waiting' ? '#8a6200' : '#000');

  return (
    <main className="main tight">
      <SourceChip source={d.source} />
      <StackedHeader
        crumbs={[{ label: 'Expansion', to: '/decide/expand' }, { label: `Opening branch ${d.branch}` }]}
        stamp={<DataStamp res={res} data={d} />}
        title={`Opening branch ${d.branch} · ${d.zip}, ${d.name}`}
        right={`playbook from ${d.playbook_from} · ${d.steps} steps`}
      />

      <div>
        <Kicker>Blockers · cleared by the agent, decided by people</Kicker>
        <div className="headline-row">
          <h1 className="headline" style={{ marginTop: 12, lineHeight: 1.25 }}>{d.headline}</h1>
          <AskWhy source={d.source} lines={[
            `Opens ${wdDayMon(d.opens)}, was ${wdDayMon(d.was)}: ${movedUp} days sooner`,
            `${cleared} of ${d.blockers.length} blockers cleared; ${d.blockers.filter((b) => b.status === 'waiting_on_you').length} waiting on a person`,
            `Playbook of ${d.steps} steps from ${d.playbook_from}; today is ${wdDayMon(d.today)}`,
          ]} />
        </div>
      </div>

      <section aria-label="Critical path" className="gantt">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span className="label" style={{ color: '#000' }}>Critical path · {ws.length} workstreams</span>
          <span className="mono-10">W{isoWeek(weeks[0])} – W{isoWeek(weeks[weeks.length - 1])}</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 11, color: 'var(--muted)', flexWrap: 'wrap' }}>
            <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 12, height: 8, background: '#0F766E' }} />done</span>
            <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 12, height: 8, background: '#171717' }} />on track</span>
            <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 12, height: 8, background: '#FCBB00' }} />waiting on a person</span>
            <span className="legend" style={{ fontSize: 11 }}><span className="hatch" style={{ width: 12, height: 8 }} />still to go</span>
            <span className="legend" style={{ fontSize: 11 }}><span style={{ width: 14, height: 9, border: '1px dashed #4d5353', background: 'rgba(15,118,110,0.06)' }} />time saved</span>
            <span className="legend" style={{ fontSize: 11 }}><AgentBadge />prepared by the agent</span>
          </span>
        </div>
        <div style={{ position: 'relative', marginTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: `${LEFT}px minmax(0, 1fr)`, height: 18, alignItems: 'center' }}>
            <span className="label">Workstream · owner</span>
            <div className="mono-10" style={{ display: 'grid', gridTemplateColumns: `repeat(${nWeeks}, minmax(0, 1fr))` }}>
              {weeks.map((wk) => <span key={wk.getTime()} style={{ borderLeft: '1px solid var(--border)', paddingLeft: 6, whiteSpace: 'nowrap', overflow: 'hidden' }}><span style={{ color: '#000' }}>W{isoWeek(wk)}</span> {dayMon(iso(wk))}</span>)}
            </div>
          </div>
          <span aria-hidden="true" style={{ position: 'absolute', left: LEFT, width: `calc((100% - ${LEFT}px) * ${todayPct.toFixed(5)})`, top: 44, bottom: 0, background: 'rgba(237,240,242,0.55)' }} />
          <div style={{ height: 26 }} />
          <div style={{ position: 'relative' }}>
            {ws.map((w) => {
              const left = x(w.start);
              const width = `${((daysBetween(w.start, w.end) / span) * 100).toFixed(3)}%`;
              const endPct = daysBetween(t0, w.end) / span;
              const prog = w.progress ? w.progress[0] / w.progress[1] : undefined;
              return (
                <div key={w.name} data-workstream className="gantt-row" style={{ gridTemplateColumns: `${LEFT}px minmax(0, 1fr)` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, paddingRight: 12 }}>
                    <span style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', marginRight: 'auto', overflow: 'hidden', textOverflow: 'ellipsis' }}>{w.name}</span>
                    {w.agent && <AgentBadge />}
                    <span className="owner-chip"><span className="sq s6" style={{ background: roleColor(w.owner) }} />{roleShort(w.owner)}</span>
                  </div>
                  <div className="gantt-lane">
                    {w.status === 'todo' ? (
                      <span className="hatch" style={{ position: 'absolute', left, width, top: 12, height: 10 }} />
                    ) : prog != null ? (
                      <>
                        <span style={{ position: 'absolute', left, width: `calc(${width} * ${prog})`, top: 12, height: 10, background: barColor(w.status) }} />
                        <span className="hatch" style={{ position: 'absolute', left: `calc(${left} + ${width} * ${prog})`, width: `calc(${width} * ${1 - prog})`, top: 12, height: 10 }} />
                      </>
                    ) : (
                      <span style={{ position: 'absolute', left, width, top: 12, height: 10, background: barColor(w.status) }} />
                    )}
                    <span style={{ position: 'absolute', left: `calc(${left} - 1px)`, top: 8, width: 2, height: 18, background: capColor(w.status) }} />
                    <span style={{ position: 'absolute', left: `calc(${(endPct * 100).toFixed(3)}% - 1px)`, top: 8, width: 2, height: 18, background: capColor(w.status) }} />
                    {w.saved_d != null && <span className="saved" style={{ position: 'absolute', left: `${(endPct * 100).toFixed(3)}%`, width: `${((w.saved_d / span) * 100).toFixed(3)}%`, top: 9, height: 16 }}>−{w.saved_d} d</span>}
                    {w.status === 'waiting' && w.due && <span className="mono" style={{ position: 'absolute', left: `calc(${(endPct * 100).toFixed(3)}% + 8px)`, top: 9, height: 16, display: 'flex', alignItems: 'center', fontSize: 10, fontWeight: 600, color: '#6b4a00', whiteSpace: 'nowrap' }}>due {wdDayMon(w.due)}</span>}
                    {w.progress && <span className="mono-10" style={{ position: 'absolute', left: `calc(${(endPct * 100).toFixed(3)}% + 8px)`, top: 9, height: 16, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' }}>{w.progress[0]} of {w.progress[1]} d</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <span style={{ position: 'absolute', left: `calc(${LEFT}px + (100% - ${LEFT}px) * ${todayPct.toFixed(5)})`, top: 22, bottom: 0, width: 1, background: '#171717' }} />
          <span className="mono" style={{ position: 'absolute', left: `calc(${LEFT}px + (100% - ${LEFT}px) * ${todayPct.toFixed(5)})`, top: 21, transform: 'translateX(-50%)', height: 18, padding: '0 7px', borderRadius: 2, background: '#171717', color: '#fff', fontSize: 10, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' }}>today · {wdDayMon(d.today)}</span>
          <span style={{ position: 'absolute', left: `calc(${LEFT}px + (100% - ${LEFT}px) * ${opensPct.toFixed(5)} - 1px)`, top: 22, bottom: 0, width: 2, background: '#0F766E' }} />
          <span className="mono" style={{ position: 'absolute', left: `calc(${LEFT}px + (100% - ${LEFT}px) * ${opensPct.toFixed(5)} + 1px)`, top: 21, transform: 'translateX(-100%)', height: 18, padding: '0 8px', borderRadius: 2, background: '#0F766E', color: '#fff', fontSize: 10, fontWeight: 600, display: 'flex', alignItems: 'center', whiteSpace: 'nowrap' }}>opens {dayMon(d.opens)} <span style={{ fontWeight: 400, marginLeft: 6 }}>(was {dayMon(d.was)})</span></span>
        </div>
      </section>

      <section aria-label="Blockers" className="blockers">
        {d.blockers.map((b) => {
          const S = b.status === 'cleared'
            ? { chip: 'Cleared', cls: 'teal', border: 'var(--border)', ring: 'none', bg: '#fff', daysC: '#0F766E', days: b.saved_d != null ? `−${b.saved_d} days` : '' }
            : b.status === 'waiting_on_you'
              ? { chip: 'Waiting on you', cls: 'amber', border: '#171717', ring: '0 0 0 1px #171717', bg: '#fffcf5', daysC: '#6b4a00', days: b.due ? `due ${weekday(b.due)}` : '' }
              : { chip: 'In progress', cls: 'grey', border: 'var(--border)', ring: 'none', bg: '#fff', daysC: '#000', days: '' };
          const match = ws.find((w) => w.name.toLowerCase() === b.title.toLowerCase());
          const prog = match?.progress;
          const days = S.days || (prog ? `${prog[0]} of ${prog[1]} d` : '');
          const decided = `${roleLabel(b.decided_by)}${b.status === 'cleared' ? ' approved' : ''}`;
          return (
            <article key={b.id} data-blocker className="blocker" style={{ borderColor: S.border, boxShadow: S.ring, background: S.bg }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="mono-10">{b.id}</span>
                <span className={`chip ${S.cls}`} style={{ padding: '2px 6px', height: 'auto' }}>{S.chip}</span>
                <span className="mono" style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: S.daysC }}>{days}</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.3 }}>{b.title}</div>
              {b.status === 'in_progress' && prog && <div style={{ height: 4, background: 'var(--muted-2)', position: 'relative' }}><span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${((prog[0] / prog[1]) * 100).toFixed(1)}%`, background: '#171717' }} /></div>}
              <div style={{ fontSize: 12, lineHeight: '18px', color: 'var(--muted)' }}><span className="label">Was</span> {b.was}</div>
              <div style={{ fontSize: 12, lineHeight: '18px' }}><span className="label" style={{ color: '#5a48c0' }}>Agent</span> {b.agent}</div>
              <div style={{ marginTop: 'auto', paddingTop: 9, borderTop: '1px solid var(--muted-2)', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--ink-2)' }}>
                <span className="sq s7" style={{ background: roleColor(b.decided_by) }} /><span>{decided}</span>
                <span className="mono" style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5, height: 20, padding: '0 7px', border: '1px solid var(--border)', borderRadius: 2, background: '#fff', fontSize: 10, color: 'var(--ink-2)', whiteSpace: 'nowrap' }}>
                  {b.surface === 'inbox' ? <InboxIcon /> : b.surface === 'notch' ? <NotchIcon /> : <DigestIcon />}
                  {b.surface.replace('_', ' ')}
                </span>
              </div>
            </article>
          );
        })}
      </section>

      <Verdict strong="Every opening teaches the next." rest={`${d.playbook_from[0].toUpperCase() + d.playbook_from.slice(1)} hit the same blockers; their approved records are why the agent saw these coming.`}>
        <NextLink to="/improve/history" arrow={false}>Approve opening plan</NextLink>
      </Verdict>
    </main>
  );
}
