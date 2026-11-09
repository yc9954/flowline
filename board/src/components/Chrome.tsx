// Shared page chrome: header with breadcrumb + stamp + Share/Export, kicker, stat tiles, verdict bar,
// source chip and the "Ask why" popover.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { Loaded, Origin } from '../lib/api';
import { useBoard, useBoardName } from '../lib/board';
import { dayTime, sourceLabel } from '../lib/format';
import { ArrowRight, ExportIcon, ShareIcon } from './Icons';

/** Breadcrumb after the board's own crumb (which `Crumbs` prepends). `to` is board-relative ("/know/waits"). */
export interface Crumb { label: string; to?: string }

export function Stamp({ origin, at, label = 'recomputed', extra, error }: { origin: Origin | 'offline'; at?: string | Date; label?: string; extra?: string; error?: string }) {
  const when = at ? dayTime(at) : '';
  if (origin === 'offline') return <span className="stamp" title={error}><span className="dot fixture" />API offline{extra ? ` · ${extra}` : ''}</span>;
  if (origin === 'fixture') {
    const why = error === 'forced' ? 'forced' : error && /shape/.test(error) ? 'API shape mismatch' : 'API offline';
    return <span className="stamp" title={error}><span className="dot fixture" />fixture · {why}{extra ? ` · ${extra}` : ''}</span>;
  }
  return <span className="stamp"><span className="dot" />{label} {when}{extra ? ` · ${extra}` : ''}</span>;
}

/** Stamp from the page's own timestamp (`recomputed_at` / `calibrated_at`) when it has one, else the fetch time. */
export function DataStamp({ res, data, extra }: { res: Loaded<unknown>; data: { recomputed_at?: string; calibrated_at?: string }; extra?: string }) {
  const own = data.recomputed_at ?? data.calibrated_at;
  return <Stamp origin={res.origin} error={res.error} at={own ?? res.fetchedAt} label={own ? 'recomputed' : 'fetched'} extra={extra} />;
}

export function HeaderButtons() {
  return (
    <>
      <button type="button" className="btn"><ShareIcon />Share</button>
      <button type="button" className="btn"><ExportIcon />Export</button>
    </>
  );
}

/** The board's name (from GET /api/boards/{id}) leads every breadcrumb; the rest comes from the page. */
export function Crumbs({ items }: { items: Crumb[] }) {
  const { path } = useBoard();
  const { name } = useBoardName();
  const all: Crumb[] = [{ label: name, to: '/know/waits' }, ...items];
  return (
    <nav aria-label="Breadcrumb" className="crumbs">
      {all.map((c, i) => (
        <span key={i} style={{ display: 'contents' }}>
          {i > 0 && <span aria-hidden="true">/</span>}
          {i === all.length - 1 ? <span aria-current="page" className="current">{c.label}</span> : c.to ? <Link to={path(c.to)}>{c.label}</Link> : <span>{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

/** One-line header (Plans/Board/Measure/Loop style). */
export function PageHeader({ crumbs, stamp }: { crumbs: Crumb[]; stamp: ReactNode }) {
  return (
    <header className="page-header">
      <Crumbs items={crumbs} />
      {stamp}
      <span className="vsep" />
      <HeaderButtons />
    </header>
  );
}

/** Two-row header (Expand/Unblock/Ontology/ModelCheck style): crumbs row + title row. */
export function StackedHeader({ crumbs, stamp, title, right, children }: { crumbs: Crumb[]; stamp: ReactNode; title: ReactNode; right?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-header stacked">
      <div className="row">
        <Crumbs items={crumbs} />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          {stamp}
          <span className="vsep" style={{ margin: '0 2px' }} />
          <button type="button" className="btn sm"><ShareIcon size={12} />Share</button>
          <button type="button" className="btn sm"><ExportIcon size={12} />Export</button>
        </div>
      </div>
      <div className="row2">
        <span className="page-title">{title}</span>
        {children}
        {right && <span style={{ marginLeft: 'auto' }} className="mono-11">{right}</span>}
      </div>
    </header>
  );
}

export function Kicker({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="kicker">
      <span className="label">{children}</span>
      <span className="hair" />
      {right}
    </div>
  );
}

export function Stat({ label, value, sub, soft, style, attrs }: { label: ReactNode; value: ReactNode; sub?: ReactNode; soft?: boolean; style?: React.CSSProperties; attrs?: Record<string, string> }) {
  return (
    <div className={`stat${soft ? ' soft' : ''}`} style={style} {...attrs}>
      <span className="label">{label}</span>
      <span className="v">{value}</span>
      {sub != null && <span className="s">{sub}</span>}
    </div>
  );
}

export function SourceChip({ source }: { source?: string }) {
  const l = sourceLabel(source);
  if (!l) return null;
  return <span className={`source-chip ${l.toLowerCase()}`} title={`This page's numbers are ${l.toLowerCase()}, not measured.`}>{l}</span>;
}

export function Verdict({ strong, rest, children }: { strong: ReactNode; rest: ReactNode; children: ReactNode }) {
  return (
    <div className="verdict">
      <p><strong>{strong}</strong> {rest}</p>
      {children}
    </div>
  );
}

/** Primary "next" button; `to` is board-relative. */
export function NextLink({ to, children, arrow = true }: { to: string; children: ReactNode; arrow?: boolean }) {
  const { path } = useBoard();
  return <Link to={path(to)} className="btn-primary">{children}{arrow && <ArrowRight />}</Link>;
}

/** A plain link that stays inside the current board; `to` is board-relative. */
export function BLink({ to, className, children, ...rest }: { to: string; className?: string; children: ReactNode; title?: string; style?: React.CSSProperties; 'aria-pressed'?: boolean }) {
  const { path } = useBoard();
  return <Link to={path(to)} className={className} {...rest}>{children}</Link>;
}

/** "Ask why" — a static popover with the source label and the records/weeks behind the headline. */
export function AskWhy({ source, lines, note }: { source?: string; lines: string[]; note?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);
  const src = source ?? 'unknown';
  return (
    <span className="askwhy" ref={ref}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Ask why</button>
      {open && (
        <div className="pop" role="dialog" aria-label="Why this number">
          <div className="label"><span>Behind this number</span><span className="src">source · {src}</span></div>
          <ul>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
          <div className="note">{note ?? (src === 'measured'
            ? 'Computed by the API from approved records. Nothing on this page is typed in.'
            : src === 'simulated'
              ? 'Computed by Flowline-1 on this company’s records; the number is a model result, not a measurement.'
              : 'Prototype data in the shared shapes, used until the model has computed real numbers.')}</div>
        </div>
      )}
    </span>
  );
}

export function Loading({ what }: { what: string }) {
  return <div className="loading">loading {what}…</div>;
}
