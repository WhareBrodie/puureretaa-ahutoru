import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, formatDate } from '../api';
import { formatMoney } from '../utils/filaments';
import ProjectFormModal from '../components/ProjectFormModal';

export default function ProjectDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [showEdit, setShowEdit] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    api.projects.get(id)
      .then(setProject)
      .catch((err) => setError(err.message));
  };

  useEffect(load, [id]);

  const handleDelete = async () => {
    if (!window.confirm(`Delete project "${project.name}"? Prints will stay but lose this assignment.`)) {
      return;
    }
    try {
      await api.projects.remove(id);
      navigate('/prints/projects');
    } catch (err) {
      setError(err.message);
    }
  };

  if (error) return <div className="card danger">{error}</div>;
  if (!project) return <div className="card muted">Loading project…</div>;

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/prints/projects" className="muted back-link">← Back to projects</Link>
          <h1>{project.name}</h1>
          <p>{project.print_count || 0} prints in this project</p>
        </div>
        <div className="toolbar">
          <button type="button" className="secondary danger-text" onClick={handleDelete}>Delete</button>
          <button type="button" onClick={() => setShowEdit(true)}>Edit</button>
        </div>
      </div>

      <div className="card project-detail-header">
        <div>
          <div className="stat-label">Project name</div>
          <div className="project-detail-name">{project.name}</div>
        </div>
        <div>
          <div className="stat-label">Project cost</div>
          <div className="project-detail-cost">
            {project.total_cost != null ? formatMoney(project.total_cost) : '—'}
          </div>
        </div>
      </div>

      {project.notes && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <div className="stat-label">Notes</div>
          <p style={{ margin: '0.35rem 0 0' }}>{project.notes}</p>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Prints</h2>
        <div className="project-print-list">
          {(project.prints || []).map((print) => (
            <div key={print.id} className="project-print-item">
              <div className="project-card-icon small" aria-hidden="true">
                <span /><span /><span /><span />
              </div>
              <div className="project-print-main">
                <strong>{print.title}</strong>
                <div className="muted project-print-sub">
                  {print.needs_review ? 'Needs review' : print.status}
                  {' · '}
                  {print.total_cost != null ? formatMoney(print.total_cost) : '—'}
                </div>
              </div>
              <div className="project-print-date muted">
                {formatDate(print.started_at || print.created_at)}
              </div>
            </div>
          ))}
        </div>
        {!project.prints?.length && <p className="muted">No prints assigned to this project yet.</p>}
      </div>

      {showEdit && (
        <ProjectFormModal
          project={project}
          onClose={() => setShowEdit(false)}
          onSaved={() => {
            setShowEdit(false);
            load();
          }}
        />
      )}
    </>
  );
}
