import { useEffect, useState } from 'react';
import { api } from '../api';

export default function EditPrintModal({ printJob, onClose, onSaved }) {
  const [title, setTitle] = useState(printJob?.title || '');
  const [projectId, setProjectId] = useState(printJob?.project_id ? String(printJob.project_id) : '');
  const [projects, setProjects] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    api.projects.list()
      .then((data) => setProjects(data.projects || []))
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    setTitle(printJob?.title || '');
    setProjectId(printJob?.project_id ? String(printJob.project_id) : '');
  }, [printJob]);

  const submit = async (event) => {
    event.preventDefault();
    try {
      await api.prints.update(printJob.id, {
        title,
        project_id: projectId ? Number(projectId) : null,
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Edit print</h2>
        {error && <div className="danger">{error}</div>}
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Project
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">No project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </label>
        <div className="toolbar">
          <button type="submit">Save changes</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
