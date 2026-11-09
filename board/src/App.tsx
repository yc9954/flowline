import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Shell } from './components/Shell';
import { ErrorBoundary } from './components/ErrorBoundary';
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

function Guard({ children }: { children: React.ReactNode }) {
  const loc = useLocation();
  return <ErrorBoundary key={loc.pathname}>{children}</ErrorBoundary>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/surfaces" element={<Guard><SurfacesPage /></Guard>} />
      <Route element={<Shell />}>
        <Route path="/" element={<Navigate to="/know/waits" replace />} />
        <Route path="/decide/expand" element={<Guard><ExpandPage /></Guard>} />
        <Route path="/decide/opening" element={<Guard><OpeningPage /></Guard>} />
        <Route path="/improve/plans" element={<Guard><PlansPage /></Guard>} />
        <Route path="/improve/results" element={<Guard><ResultsPage /></Guard>} />
        <Route path="/improve/history" element={<Guard><HistoryPage /></Guard>} />
        <Route path="/know/knowledge" element={<Guard><KnowledgePage /></Guard>} />
        <Route path="/know/waits" element={<Guard><WaitsPage /></Guard>} />
        <Route path="/know/records" element={<Guard><RecordsPage /></Guard>} />
        <Route path="/know/records/:id" element={<Guard><RecordsPage /></Guard>} />
        <Route path="/trust/model" element={<Guard><ModelPage /></Guard>} />
        <Route path="/run/fleet" element={<Guard><FleetPage /></Guard>} />
        <Route path="*" element={<Navigate to="/know/waits" replace />} />
      </Route>
    </Routes>
  );
}
