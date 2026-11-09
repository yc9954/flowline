import { NavLink, Outlet } from 'react-router-dom';
import { useOpening, useRecordCount } from '../lib/api';
import { Logo } from './Icons';

const groups: { name: string; items: { to: string; label: string }[] }[] = [
  { name: 'Decide', items: [{ to: '/decide/expand', label: 'Where to open next' }, { to: '/decide/opening', label: 'Opening branch' }] },
  { name: 'Improve', items: [{ to: '/improve/plans', label: 'Plans to test' }, { to: '/improve/results', label: 'Results' }, { to: '/improve/history', label: 'Process history' }] },
  { name: 'Know', items: [{ to: '/know/knowledge', label: 'Company knowledge' }, { to: '/know/waits', label: 'Where work waits' }, { to: '/know/records', label: 'Approved records' }] },
  { name: 'Trust', items: [{ to: '/trust/model', label: 'Model check' }] },
  { name: 'Run', items: [{ to: '/run/fleet', label: 'Agents on desks' }] },
];

export function Sidebar() {
  const records = useRecordCount();
  const opening = useOpening();
  const branch = opening?.data.branch;
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-logo"><Logo /></span>
        <div>
          <div className="sidebar-name">Flowline</div>
          <div className="sidebar-board">Northwind Fitness</div>
        </div>
      </div>
      {groups.map((g) => (
        <div key={g.name} style={{ display: 'contents' }}>
          <div className="sidebar-group">{g.name}</div>
          {g.items.map((it) => (
            <NavLink key={it.to} to={it.to} className={({ isActive }) => `nav${isActive ? ' active' : ''}`}>
              {it.to === '/decide/opening' && branch != null ? `Opening branch ${branch}` : it.label}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="sidebar-foot">
        <div><div className="label-9">Records</div><div className="num">{records != null ? records.toLocaleString('en-US') : '—'}</div></div>
        <div><div className="label-9">Screens shared</div><div className="num">0</div></div>
      </div>
    </aside>
  );
}

export function Shell() {
  return (
    <div className="shell">
      <Sidebar />
      <Outlet />
    </div>
  );
}
