import { useEffect } from 'react';
import { Link, NavLink, Outlet, useParams } from 'react-router-dom';
import { useOpening, useRecordCount } from '../lib/api';
import { BoardProvider, useBoard, useBoardInfo } from '../lib/board';
import { industryLabel } from '../lib/industry';
import { Logo } from './Icons';

const groups: { name: string; items: { to: string; label: string }[] }[] = [
  { name: 'Decide', items: [{ to: '/decide/expand', label: 'Where to open next' }, { to: '/decide/opening', label: 'Opening the next site' }] },
  { name: 'Improve', items: [{ to: '/improve/plans', label: 'Plans to test' }, { to: '/improve/results', label: 'Results' }, { to: '/improve/history', label: 'Process history' }] },
  { name: 'Know', items: [{ to: '/know/knowledge', label: 'Company knowledge' }, { to: '/know/waits', label: 'Where work waits' }, { to: '/know/records', label: 'Approved records' }] },
  { name: 'Trust', items: [{ to: '/trust/model', label: 'Model check' }] },
  { name: 'Run', items: [{ to: '/run/fleet', label: 'Agents on desks' }, { to: '/people', label: 'People & invites' }] },
];

export function Sidebar() {
  const { id, path } = useBoard();
  const info = useBoardInfo();
  const board = info?.kind === 'data' ? info.board : null;
  const records = useRecordCount(board?.records);
  const opening = useOpening();
  const branch = opening?.kind === 'data' ? opening.data.branch : null;
  const name = board?.name ?? (info?.kind === 'missing' ? `${id} · no such board` : id);
  const sub = board ? industryLabel(board.industry) || (board.city ?? '') : info?.kind === 'offline' ? 'API offline' : '';
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-logo"><Logo /></span>
        <div style={{ minWidth: 0 }}>
          <div className="sidebar-name">Flowline</div>
          <div className="sidebar-board ellipsis" title={sub ? `${name} · ${sub}` : name}>{name}</div>
        </div>
      </div>
      {groups.map((g) => (
        <div key={g.name} style={{ display: 'contents' }}>
          <div className="sidebar-group">{g.name}</div>
          {g.items.map((it) => (
            <NavLink key={it.to} to={path(it.to)} className={({ isActive }) => `nav${isActive ? ' active' : ''}`}>
              {it.to === '/decide/opening' ? (branch ? `Opening site ${branch}` : 'Opening the next site') : it.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="sidebar-foot">
        <div><div className="label-9">Records</div><div className="num">{records != null ? records.toLocaleString('en-US') : '—'}</div></div>
        <div><div className="label-9">Screens shared</div><div className="num">0</div></div>
      </div>
      <Link to="/" className="sidebar-all">← all boards</Link>
    </aside>
  );
}

/** Sets the board from the URL for everything below; keeps the tab title on the board's name. */
export function BoardScope({ children }: { children: React.ReactNode }) {
  const { boardId = '' } = useParams();
  return <BoardProvider id={boardId}><Title />{children}</BoardProvider>;
}

function Title() {
  const { id } = useBoard();
  const info = useBoardInfo();
  const name = info?.kind === 'data' ? info.board.name : id;
  useEffect(() => { document.title = `Flowline — ${name}`; }, [name]);
  return null;
}

export function Shell() {
  return (
    <BoardScope>
      <div className="shell">
        <Sidebar />
        <Outlet />
      </div>
    </BoardScope>
  );
}
