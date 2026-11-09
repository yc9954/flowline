import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useOntology } from '../lib/api';
import { layoutGraph, LANE_H, LANE_TOP, NODE_H, NODE_W, ROLE_COL } from '../lib/graph';
import { dayTime, h1, minutes, pct, roleColor, roleLabel } from '../lib/format';
import type { OntNode } from '../lib/types';
import { AskWhy, Loading, SourceChip, StackedHeader, Stamp } from '../components/Chrome';
import { NotReady } from '../components/NotReady';
import { KindGlyph } from '../components/Icons';
import './Knowledge.css';

export default function KnowledgePage() {
  const res = useOntology();
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [view, setView] = useState({ w: 0, h: 0, sx: 0, sy: 0 });
  const scroller = useRef<HTMLElement>(null);

  const d = res?.kind === 'data' ? res.data : undefined;
  useEffect(() => {
    if (d && selected == null) {
      const pick = d.nodes.find((n) => n.bottleneck) ?? d.nodes.find((n) => n.critical_path) ?? d.nodes[0];
      if (pick) setSelected(pick.id);
    }
  }, [d, selected]);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const upd = () => setView({ w: el.clientWidth, h: el.clientHeight, sx: el.scrollLeft, sy: el.scrollTop });
    upd();
    const ro = new ResizeObserver(upd); ro.observe(el);
    el.addEventListener('scroll', upd);
    return () => { ro.disconnect(); el.removeEventListener('scroll', upd); };
  }, [d]);

  const L = useMemo(() => (d ? layoutGraph(d, selected, view.w ? view.w / zoom : undefined) : null), [d, selected, view.w, zoom]);
  // first layout on a narrow screen: start at "fit" so the whole path is visible
  const fitted = useRef(false);
  useEffect(() => {
    if (!L || !view.w || fitted.current) return;
    fitted.current = true;
    if (L.naturalWidth > view.w) setZoom(Math.max(0.5, Math.floor((view.w / L.naturalWidth) * 20) / 20));
  }, [L, view.w]);
  if (res && res.kind !== 'data') return <NotReady res={res} crumbs={[{ label: 'Know' }, { label: 'Company knowledge' }]} what="company knowledge" className="main canvas" />;
  if (!res || !d || !L) return <main className="main canvas"><Loading what="company knowledge" /></main>;

  const sel = selected ? d.nodes.find((n) => n.id === selected) ?? null : null;
  const selLane = sel ? d.roles.findIndex((r) => r.role === sel.role) : -1;
  const roleCount = d.roles.length, steps = d.nodes.filter((n) => n.kind !== 'event').length;
  const decisions = d.nodes.filter((n) => n.kind === 'decision').length, backs = d.edges.filter((e) => e.kind === 'back').length;
  const inEdges = sel ? d.edges.filter((e) => e.to === sel.id && e.kind !== 'back') : [];
  const outEdges = sel ? d.edges.filter((e) => e.from === sel.id) : [];
  const nameOf = (id: string) => d.nodes.find((n) => n.id === id)?.name ?? id;
  const fit = () => setZoom(L.naturalWidth > view.w && view.w ? Math.max(0.5, Math.floor((view.w / L.naturalWidth) * 20) / 20) : 1);
  const canvasW = L.width * zoom, canvasH = L.height * zoom;

  return (
    <main className="main canvas">
      <SourceChip source={d.source} />
      <StackedHeader
        crumbs={[{ label: 'Know' }, { label: 'Company knowledge' }]}
        stamp={<Stamp origin={res.origin} error={res.error} at={d.recomputed_at} extra={`v${d.version}`} />}
        title={<>Company knowledge <span style={{ color: 'var(--muted)', fontWeight: 400 }}>· {d.records_used} records</span></>}
      >
        <span className="kn-legend">
          <span><KindGlyph kind="event" stroke="#171717" />event</span>
          <span><KindGlyph kind="step" stroke="#171717" />step</span>
          <span><KindGlyph kind="decision" stroke="#171717" />decision</span>
          <span><KindGlyph kind="skill" />skill</span>
          <span className="vsep" style={{ height: 14, margin: 0 }} />
          <span><span style={{ width: 18, borderTop: '1.5px solid #9aa1a6' }} />then</span>
          <span><span style={{ width: 18, borderTop: '2px dashed #C24D32' }} />sent back</span>
          <span><span style={{ width: 18, height: 5, background: '#FCBB00', position: 'relative' }}><span style={{ position: 'absolute', left: 0, right: 0, top: 2, height: 1, background: '#171717' }} /></span>long wait</span>
          <span><span style={{ width: 12, height: 10, border: '1px solid #171717', boxShadow: '0 0 0 1px #171717', borderRadius: 2, background: '#fffcf5' }} />selected</span>
        </span>
      </StackedHeader>

      <div className="headline-row" style={{ alignItems: 'baseline' }}>
        <h1 className="headline" style={{ margin: 0, fontSize: 26, lineHeight: 1.25 }}>{d.headline}</h1>
        <AskWhy source={d.source} lines={[
          `Learned from ${d.records_used} approved records · version ${d.version}, recomputed ${dayTime(d.recomputed_at)}`,
          `${steps} steps across ${roleCount} roles, ${decisions} decisions, ${backs} ways back; nothing was drawn by hand`,
          `Knowledge: ${d.counts.cases} cases · ${d.counts.files} files · ${d.counts.rules} rules · ${d.counts.skills} skills · ${d.counts.customers} customers`,
        ]} />
      </div>

      <div className="kn-grid">
        <section aria-label="Process graph" className="kn-canvas" ref={scroller}>
          <div style={{ position: 'relative', width: canvasW, height: canvasH }}>
            <div style={{ position: 'absolute', left: 0, top: 0, width: L.width, height: L.height, transform: `scale(${zoom})`, transformOrigin: '0 0' }}>
              {/* lanes */}
              {L.lanes.map((ln, i) => (
                <div key={ln.role} data-lane={ln.role} style={{ position: 'absolute', left: 0, right: 0, top: ln.y, height: LANE_H }}>
                  <div style={{ position: 'absolute', left: ROLE_COL, right: 0, top: 0, height: LANE_H, background: i % 2 ? '#fbfcfd' : '#fff', borderTop: '1px solid #edf0f2' }} />
                  <div className="kn-lane-head" style={{ top: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span className="sq" style={{ background: roleColor(ln.role) }} /><span style={{ fontSize: 12, fontWeight: 600 }}>{roleLabel(ln.role)}</span></div>
                    <div className="mono-10" style={{ marginTop: 4, paddingLeft: 14 }}>{ln.steps} step{ln.steps === 1 ? '' : 's'}</div>
                    {ln.external && <div className="kn-lane-tag" style={{ color: '#6b4a00' }}>external</div>}
                    {i === selLane && <div className="kn-lane-tag" style={{ color: '#000' }}>selected</div>}
                  </div>
                </div>
              ))}
              <div className="label" style={{ position: 'absolute', left: 0, top: 0, width: ROLE_COL, height: LANE_TOP, padding: '14px 0 0 12px', background: '#f7f8f9' }}>Role</div>
              <div style={{ position: 'absolute', left: 0, top: LANE_TOP + L.lanes.length * LANE_H, width: ROLE_COL, bottom: 0, background: '#f7f8f9' }} />
              <div style={{ position: 'absolute', left: ROLE_COL - 1, top: 0, bottom: 0, width: 1, background: 'var(--border)' }} />
              <span className="mono-10" style={{ position: 'absolute', left: ROLE_COL + 16, top: 10 }}>Median path · {d.records_used} approved records · left to right in time</span>

              {/* edges */}
              <svg width={L.width} height={L.height} viewBox={`0 0 ${L.width} ${L.height}`} style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible' }} aria-hidden="true">
                <defs>
                  <marker id="m-f" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 1 L10 5 L0 9 z" fill="#9aa1a6" /></marker>
                  <marker id="m-hot" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 1 L10 5 L0 9 z" fill="#171717" /></marker>
                  <marker id="m-back" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 1 L10 5 L0 9 z" fill="#C24D32" fillOpacity="0.55" /></marker>
                  <marker id="m-backhot" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 1 L10 5 L0 9 z" fill="#C24D32" /></marker>
                </defs>
                {L.edges.filter((e) => e.longWait).map((e, i) => <path key={`w${i}`} d={e.d} fill="none" stroke="#FCBB00" strokeWidth="7" strokeLinejoin="round" />)}
                {L.edges.map((e, i) => {
                  const stub = !e.to;
                  if (e.back) return <path key={i} data-edge-back d={e.d} fill="none" stroke="#C24D32" strokeOpacity={e.hot ? 1 : 0.55} strokeWidth={e.hot ? 2 : 1.5} strokeDasharray={e.hot ? '6 4' : '5 4'} markerEnd={`url(#${e.hot ? 'm-backhot' : 'm-back'})`} />;
                  return <path key={i} d={e.d} fill="none" stroke={e.hot ? '#171717' : '#9aa1a6'} strokeWidth={e.hot ? 2 : 1.25} markerEnd={stub ? undefined : `url(#${e.hot ? 'm-hot' : 'm-f'})`} />;
                })}
              </svg>

              {/* edge labels */}
              {L.edges.map((e, i) => {
                if (!e.label) return null;
                const text = e.edge.label;
                if (!text) return null;
                const cls = e.back ? (e.hot ? 'kn-lbl back-hot' : 'kn-lbl back') : e.longWait ? 'kn-lbl wait' : e.parallel ? 'kn-lbl par' : 'kn-lbl';
                const tx = e.label.align === 'center' ? 'translateX(-50%)' : e.label.align === 'right' ? 'translateX(-100%)' : 'none';
                return <span key={`l${i}`} className={cls} style={{ left: e.label.x, top: e.label.y, transform: tx }}>{text}</span>;
              })}

              {/* nodes */}
              {[...L.placed.values()].map((p) => <NodeBox key={p.node.id} n={p.node} x={p.x} y={p.y} selected={p.node.id === selected} onSelect={() => setSelected(p.node.id)} />)}

              {/* mini-map + zoom */}
              <div className="kn-mini" role="group" aria-label="Mini-map and zoom" style={{ transform: `scale(${1 / zoom})`, transformOrigin: '100% 100%', right: 12 / zoom, bottom: 12 / zoom }}>
                <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--hair)' }}>
                  <button type="button" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.1).toFixed(2)))}><svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#000" strokeWidth="1.5"><path d="M1 5h8" /></svg></button>
                  <span className="mono" style={{ width: 52, textAlign: 'center', fontSize: 10, borderRight: '1px solid var(--hair)', lineHeight: '24px' }}>{Math.round(zoom * 100)}%</span>
                  <button type="button" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(2, +(z + 0.1).toFixed(2)))}><svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#000" strokeWidth="1.5"><path d="M1 5h8M5 1v8" /></svg></button>
                  <button type="button" className="fit" onClick={fit}>Fit</button>
                </div>
                <div style={{ padding: 6 }}>
                  <div style={{ position: 'relative' }}>
                    <svg width="164" height={Math.round((164 * L.height) / (L.width - ROLE_COL))} viewBox={`${ROLE_COL} 0 ${L.width - ROLE_COL} ${L.height}`} preserveAspectRatio="none" aria-hidden="true" style={{ display: 'block' }}>
                      {L.lanes.map((ln, i) => <rect key={ln.role} x={ROLE_COL} y={ln.y} width={L.width} height={LANE_H} fill={i % 2 ? '#f2f5f6' : '#fff'} />)}
                      {[...L.placed.values()].map((p) => <rect key={p.node.id} x={p.x} y={p.y} width={NODE_W} height={NODE_H} fill={p.node.id === selected ? '#171717' : p.node.kind === 'skill' ? '#6D5BD0' : p.node.critical_path ? '#4d5353' : '#b8bec2'} />)}
                    </svg>
                    {view.w > 0 && (
                      <span aria-hidden="true" style={{ position: 'absolute', border: '1.5px solid #171717', borderRadius: 2, left: `${Math.max(0, ((view.sx / zoom - ROLE_COL) / (L.width - ROLE_COL)) * 100)}%`, width: `${Math.min(100, (view.w / zoom / (L.width - ROLE_COL)) * 100)}%`, top: `${((view.sy / zoom) / L.height) * 100}%`, height: `${Math.min(100, (view.h / zoom / L.height) * 100)}%` }} />
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section aria-label={sel ? `Selected object: ${sel.name}` : 'Inspector'} className="kn-inspector">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span className="label" style={{ color: '#000' }}>Inspector</span><span className="hair" /><span className="mono-10">{sel ? '1 selected' : 'nothing selected'}</span></div>
          {sel && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 30, height: 30, borderRadius: 4, background: sel.kind === 'skill' ? '#6D5BD0' : '#171717', display: 'flex', alignItems: 'center', justifyContent: 'center', flex: '0 0 30px' }}><KindGlyph kind={sel.kind} stroke="#fff" size={14} /></span>
                <div style={{ minWidth: 0 }}>
                  <div className="label-9">{sel.kind}{sel.kind === 'skill' ? ' · agent' : ''} · {roleLabel(sel.role)}</div>
                  <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.2 }}>{sel.name}</div>
                </div>
                {sel.bottleneck && <span className="chip amber" style={{ marginLeft: 'auto', padding: '3px 6px', height: 'auto' }}>Bottleneck</span>}
              </div>
              <div>
                <div className="label kn-sec">Properties</div>
                {sel.wait_before_h != null && <Prop k="Wait before it" v={h1(sel.wait_before_h)} hot={!!sel.bottleneck} />}
                {sel.median_min != null && <Prop k="Hands-on (median)" v={minutes(sel.median_min)} />}
                <Prop k="Cases through it" v={String(sel.cases)} />
                {sel.share_of_cycle != null && <Prop k="Share of cycle time" v={pct(sel.share_of_cycle)} />}
                <Prop k="On the critical path" v={sel.critical_path ? 'yes' : 'no'} />
                {sel.aliases.length > 0 && <Prop k="Also called" v={sel.aliases.join(', ')} />}
              </div>
              <div>
                <div className="label kn-sec">Path in</div>
                {inEdges.length === 0 && <div className="kn-row muted">— start of the path</div>}
                {inEdges.map((e, i) => (
                  <div key={i} className="kn-row">
                    {(e.wait_h ?? 0) > 0 && <span style={{ width: 10, height: 4, background: '#FCBB00', marginRight: 6 }} />}
                    <span>← {nameOf(e.from)}</span>
                    {(e.wait_h ?? 0) > 0 && <span className="mono" style={{ marginLeft: 'auto', fontWeight: sel.bottleneck ? 700 : 400, color: sel.bottleneck ? '#6b4a00' : '#000' }}>{h1(e.wait_h!)} wait</span>}
                  </div>
                ))}
              </div>
              <div>
                <div className="label kn-sec">Paths out</div>
                {outEdges.length === 0 && <div className="kn-row muted">— end of the path</div>}
                {outEdges.map((e, i) => (
                  <div key={i} className="kn-row" style={{ color: e.kind === 'back' ? '#C24D32' : undefined }}>
                    <span>{e.kind === 'back' ? `↩ back to ${nameOf(e.to)}` : `→ ${nameOf(e.to)}`}</span>
                    {e.share != null && <span className="mono" style={{ marginLeft: 'auto' }}>{pct(e.share)}</span>}
                  </div>
                ))}
              </div>
              {sel.rule && <div className="kn-rule">{sel.rule}</div>}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function Prop({ k, v, hot }: { k: string; v: string; hot?: boolean }) {
  return <div className="kn-row"><span className="muted">{k}</span><span className="mono" style={{ marginLeft: 'auto', textAlign: 'right', fontWeight: hot ? 700 : 400, color: hot ? '#6b4a00' : '#000' }}>{v}</span></div>;
}

function NodeBox({ n, x, y, selected, onSelect }: { n: OntNode; x: number; y: number; selected: boolean; onSelect: () => void }) {
  const skill = n.kind === 'skill';
  const crit = n.critical_path;
  const bg = selected ? '#fffcf5' : skill ? '#f7f5ff' : crit ? '#fff' : '#fcfdfd';
  const border = selected ? '#171717' : skill ? '#cfc6f7' : crit ? '#9aa1a6' : '#e1e5e7';
  const subColor = n.bottleneck ? '#6b4a00' : skill ? '#5a48c0' : '#4d5353';
  return (
    <button type="button" className="kn-node" data-node={n.id} data-node-id={n.id} aria-pressed={selected} onClick={onSelect}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H, background: bg, borderColor: border, boxShadow: selected ? '0 0 0 2px #171717, 0 6px 16px rgba(20,20,25,0.12)' : 'none' }}>
      <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: roleColor(n.role), opacity: crit || selected ? 1 : 0.45 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}><KindGlyph kind={n.kind} stroke={crit || selected ? '#171717' : '#4d5353'} /><span className="mono" style={{ fontSize: 8, letterSpacing: '0.8px', textTransform: 'uppercase', color: '#4d5353', whiteSpace: 'nowrap' }}>{n.kind}{skill ? ' · agent' : ''}</span></div>
      <div style={{ fontSize: 11, fontWeight: 600, lineHeight: '13px', marginTop: 3, color: crit || selected ? '#000' : '#30373f', textAlign: 'left' }}>{n.name}</div>
      {n.sub && <div className="mono" style={{ fontSize: 9, lineHeight: '11px', marginTop: 2, color: subColor, fontWeight: n.bottleneck ? 700 : 400, textAlign: 'left' }}>{n.sub}</div>}
    </button>
  );
}
