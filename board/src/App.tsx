// Routes. Every board page lives under /b/:boardId/…; "/" lists the boards. The old board-less paths
// (/know/waits, /surfaces, …) redirect to the demo board, `northwind`, so the recorder and old links keep working.
import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { BoardScope, Shell } from './components/Shell';
import { ErrorBoundary } from './components/ErrorBoundary';
import { fetchBoards } from './lib/board';
import ExpandPage from './pages/Expand';
import OpeningPage from './pages/Opening';
import PlansPage from './pages/Plans';
import ResultsPage from './pages/Results';
import HistoryPage from './pages/History';
import KnowledgePage from './pages/Knowledge';
import WaitsPage from './pages/Waits';
import RecordsPage from './pages/Records';
import ModelPage from './pages/Model';
import SurfacesPage from './pages/Surfaces';
import FleetPage from './pages/Fleet';
import PeoplePage from './pages/People';
import BoardsPage from './pages/Boards';

/** The board the old paths meant. */
export const LEGACY_BOARD = 'northwind';

function Guard({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  return <ErrorBoundary key={loc.pathname}>{children}</ErrorBoundary>;
}

/**
 * /know/waits → /b/northwind/know/waits, but only when that board exists. When GET /api/boards is not available
 * (API down, or an API that predates boards) the redirect still happens, so a demo against an older API keeps
 * working; when the list answers and has no `northwind`, the visitor lands on the board list instead.
 */
function LegacyRedirect() {
  const loc = useLocation();
  const [to, setTo] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetchBoards().then((r) => {
      if (!alive) return;
      const exists = r.kind === 'offline' || r.boards.some((b) => b.id === LEGACY_BOARD);
      setTo(exists ? `/b/${LEGACY_BOARD}${loc.pathname}${loc.search}${loc.hash}` : '/');
    });
    return () => { alive = false; };
  }, [loc.pathname, loc.search, loc.hash]);
  if (!to) return <div className="loading" style={{ padding: 40 }}>opening the board…</div>;
  return <Navigate to={to} replace />;
}

const LEGACY = ['/surfaces', '/decide/*', '/improve/*', '/know/*', '/trust/*', '/run/*'];

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Guard><BoardsPage /></Guard>} />
      {LEGACY.map((p) => <Route key={p} path={p} element={<LegacyRedirect />} />)}

      <Route path="/b/:boardId/surfaces" element={<BoardScope><Guard><SurfacesPage /></Guard></BoardScope>} />
      <Route path="/b/:boardId" element={<Shell />}>
        <Route index element={<Navigate to="know/waits" replace />} />
        <Route path="decide/expand" element={<Guard><ExpandPage /></Guard>} />
        <Route path="decide/opening" element={<Guard><OpeningPage /></Guard>} />
        <Route path="improve/plans" element={<Guard><PlansPage /></Guard>} />
        <Route path="improve/results" element={<Guard><ResultsPage /></Guard>} />
        <Route path="improve/history" element={<Guard><HistoryPage /></Guard>} />
        <Route path="know/knowledge" element={<Guard><KnowledgePage /></Guard>} />
        <Route path="know/waits" element={<Guard><WaitsPage /></Guard>} />
        <Route path="know/records" element={<Guard><RecordsPage /></Guard>} />
        <Route path="know/records/:id" element={<Guard><RecordsPage /></Guard>} />
        <Route path="trust/model" element={<Guard><ModelPage /></Guard>} />
        <Route path="run/fleet" element={<Guard><FleetPage /></Guard>} />
        <Route path="people" element={<Guard><PeoplePage /></Guard>} />
        <Route path="*" element={<Navigate to="know/waits" replace />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
