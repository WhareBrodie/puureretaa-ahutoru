import { NavLink, Route, Routes } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import SpoolsPage from './pages/SpoolsPage';
import SpoolDetailPage from './pages/SpoolDetailPage';
import PrintsPage from './pages/PrintsPage';
import AmsPage from './pages/AmsPage';
import StatsPage from './pages/StatsPage';
import SettingsPage from './pages/SettingsPage';

const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/spools', label: 'Spools' },
  { to: '/prints', label: 'Prints' },
  { to: '/ams', label: 'AMS' },
  { to: '/stats', label: 'Stats' },
  { to: '/settings', label: 'Settings' },
];

export default function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <strong>Pūreretā Ahutoru</strong>
            <small>Filament inventory</small>
          </div>
        </div>
        <nav>
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? 'active' : undefined)}>
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/spools" element={<SpoolsPage />} />
          <Route path="/spools/:id" element={<SpoolDetailPage />} />
          <Route path="/prints" element={<PrintsPage />} />
          <Route path="/ams" element={<AmsPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
