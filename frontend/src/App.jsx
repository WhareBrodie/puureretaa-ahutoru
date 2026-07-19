import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import DashboardPage from './pages/DashboardPage';
import FilamentsPage from './pages/FilamentsPage';
import FilamentDetailPage from './pages/FilamentDetailPage';
import InventoryPage from './pages/InventoryPage';
import SpoolDetailPage from './pages/SpoolDetailPage';
import PrintsPage from './pages/PrintsPage';
import ProjectsPage from './pages/ProjectsPage';
import ProjectDetailPage from './pages/ProjectDetailPage';
import AmsPage from './pages/AmsPage';
import StatsPage from './pages/StatsPage';
import SettingsPage from './pages/SettingsPage';

const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/filaments', label: 'Filaments' },
  { to: '/inventory', label: 'Inventory' },
  {
    label: 'Prints',
    children: [
      { to: '/prints', label: 'All prints', end: true },
      { to: '/prints?review=1', label: 'Review queue' },
      { to: '/prints/projects', label: 'Projects' },
    ],
  },
  { to: '/ams', label: 'AMS' },
  { to: '/stats', label: 'Stats' },
  { to: '/settings', label: 'Settings' },
];

function SidebarNav() {
  const location = useLocation();
  const reviewActive = location.pathname === '/prints' && location.search === '?review=1';
  const printsActive = location.pathname === '/prints' && !reviewActive;
  const projectsActive = location.pathname.startsWith('/prints/projects');

  return (
    <nav>
      {links.map((link) => (
        link.children ? (
          <div key={link.label} className="nav-group">
            <div className="nav-group-label">{link.label}</div>
            {link.children.map((child) => {
              let active = false;
              if (child.to === '/prints?review=1') active = reviewActive;
              else if (child.to === '/prints') active = printsActive;
              else if (child.to === '/prints/projects') active = projectsActive;
              return (
                <NavLink
                  key={child.to}
                  to={child.to}
                  end={child.end}
                  className={active ? 'active nav-sub' : 'nav-sub'}
                >
                  {child.label}
                </NavLink>
              );
            })}
          </div>
        ) : (
          <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? 'active' : undefined)}>
            {link.label}
          </NavLink>
        )
      ))}
    </nav>
  );
}

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
        <SidebarNav />
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/filaments" element={<FilamentsPage />} />
          <Route path="/filaments/:key" element={<FilamentDetailPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/spools" element={<Navigate to="/filaments" replace />} />
          <Route path="/spools/:id" element={<SpoolDetailPage />} />
          <Route path="/prints" element={<PrintsPage />} />
          <Route path="/prints/projects" element={<ProjectsPage />} />
          <Route path="/prints/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/ams" element={<AmsPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
