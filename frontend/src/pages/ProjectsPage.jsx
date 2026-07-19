import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { formatMoney } from '../utils/filaments';
import ProjectFormModal from '../components/ProjectFormModal';

export default function ProjectsPage() {
  const [projects, setProjects] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    api.projects.list()
      .then((data) => setProjects(data.projects || []))
      .catch((err) => setError(err.message));
  };

  useEffect(load, []);

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/prints" className="muted back-link">← Back to prints</Link>
          <h1>Projects</h1>
          <p>Group related prints and track total project cost</p>
        </div>
        <button onClick={() => setShowForm(true)}>New project</button>
      </div>

      {error && <div className="card danger">{error}</div>}

      <div className="project-grid">
        {projects.map((project) => (
          <Link key={project.id} to={`/prints/projects/${project.id}`} className="card project-card">
            <div className="project-card-icon" aria-hidden="true">
              <span /><span /><span /><span />
            </div>
            <div className="project-card-body">
              <h3>{project.name}</h3>
              <div className="project-card-meta">
                <span>{project.total_cost != null ? formatMoney(project.total_cost) : '—'}</span>
                <span className="badge spool-count">
                  {project.print_count || 0} {project.print_count === 1 ? 'print' : 'prints'}
                </span>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {!projects.length && !error && (
        <div className="card empty-state">
          <p className="muted">No projects yet. Create one to start grouping prints.</p>
        </div>
      )}

      {showForm && (
        <ProjectFormModal
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            load();
          }}
        />
      )}
    </>
  );
}
