// What a page shows instead of its data: the board has nothing yet (empty state), the board does not exist,
// or the API cannot be reached. Never fixture data.
import { Link } from 'react-router-dom';
import type { Empty, Offline } from '../lib/api';
import { useBoard, useBoardInfo } from '../lib/board';
import { dayTime } from '../lib/format';
import { PageHeader, Stamp, type Crumb } from './Chrome';

export function NotReady({ res, crumbs, what, className = 'main' }: { res: (Empty | Offline) & { retry: () => void }; crumbs: Crumb[]; what: string; className?: string }) {
  const { id, path } = useBoard();
  const info = useBoardInfo();
  const board = info?.kind === 'data' ? info.board : null;
  const missing = (res.kind === 'empty' && res.state === 'no_such_board') || info?.kind === 'missing';

  if (res.kind === 'offline') {
    return (
      <main className={className}>
        <PageHeader crumbs={crumbs} stamp={<Stamp origin="offline" error={res.error} />} />
        <div className="empty" data-empty="offline">
          <div className="label">API offline</div>
          <h1 className="headline" style={{ fontSize: 26 }}>The board cannot reach its API.</h1>
          <p className="sub">{res.status === 404 ? res.error : `No answer for ${what} (${res.error}). Nothing here is made up: the page stays empty until the API answers.`}</p>
          <div className="empty-actions">
            <button type="button" className="btn-primary" onClick={res.retry}>Retry</button>
            <Link to="/" className="btn lg">All boards</Link>
          </div>
        </div>
      </main>
    );
  }

  if (missing) {
    return (
      <main className={className}>
        <PageHeader crumbs={crumbs} stamp={<Stamp origin="api" label="checked" at={new Date()} />} />
        <div className="empty" data-empty="missing">
          <div className="label">No such board</div>
          <h1 className="headline" style={{ fontSize: 26 }}>There is no board called “{id}”.</h1>
          <p className="sub">Pick a board from the list, or set up a new company — it takes a name, an industry and a mail domain.</p>
          <div className="empty-actions">
            <Link to="/" className="btn-primary">All boards</Link>
            <Link to="/?new=1" className="btn lg">New company</Link>
          </div>
        </div>
      </main>
    );
  }

  // the board exists, the model has nothing for this page yet
  const people = board?.people ?? 0, records = board?.records ?? 0;
  const need = board?.min_records ?? null;
  const when = board?.next_fit_at ? `the first fit runs ${dayTime(board.next_fit_at)}` : need ? `the first fit runs after ${need} approved records` : 'the first fit runs the night after the first approved records arrive';
  return (
    <main className={className}>
      <PageHeader crumbs={crumbs} stamp={<Stamp origin="api" label="checked" at={new Date()} extra="no data yet" />} />
      <div className="empty" data-empty="no_data_yet">
        <div className="label">{what} · nothing yet</div>
        <h1 className="headline" style={{ fontSize: 26 }}>No approved records yet.</h1>
        <p className="sub">
          {people} {people === 1 ? 'person' : 'people'} invited, {records} {records === 1 ? 'record' : 'records'} so far; {when}.
          {' '}Each person approves their own day record in the Mac app; the board fills in from those, and from nothing else.
        </p>
        <div className="empty-actions">
          <Link to={path('/people')} className="btn-primary">Invite people</Link>
          <button type="button" className="btn lg" onClick={res.retry}>Check again</button>
        </div>
      </div>
    </main>
  );
}
