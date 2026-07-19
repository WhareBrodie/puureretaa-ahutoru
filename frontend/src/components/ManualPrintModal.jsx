import { useEffect, useState } from 'react';
import { api } from '../api';
import { compareSpoolsForSelect, formatSpoolSelectLabel } from '../utils/filaments';

export default function ManualPrintModal({ spools, onClose, onSaved }) {
  const [title, setTitle] = useState('');
  const [duration, setDuration] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projects, setProjects] = useState([]);
  const [lines, setLines] = useState([{ spool_id: '', used_g: '', material: '', ams_slot: 1 }]);
  const [error, setError] = useState('');

  useEffect(() => {
    api.projects.list()
      .then((data) => setProjects(data.projects || []))
      .catch((err) => setError(err.message));
  }, []);

  const updateLine = (index, key, value) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, [key]: value } : line)));
  };

  const submit = async (event) => {
    event.preventDefault();
    try {
      await api.prints.create({
        title,
        duration_s: duration ? Number(duration) : null,
        project_id: projectId ? Number(projectId) : null,
        usages: lines.map((line) => ({
          spool_id: line.spool_id ? Number(line.spool_id) : null,
          used_g: Number(line.used_g || 0),
          material: line.material || null,
          ams_slot: Number(line.ams_slot || 1),
        })),
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Log manual print</h2>
        {error && <div className="danger">{error}</div>}
        <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
        <label>
          Project
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">No project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </label>
        <label>Duration (seconds)<input type="number" value={duration} onChange={(e) => setDuration(e.target.value)} /></label>
        {lines.map((line, index) => (
          <div key={index} className="form-grid two">
            <label>Spool<select value={line.spool_id} onChange={(e) => updateLine(index, 'spool_id', e.target.value)}>
              <option value="">Select spool</option>
              {[...spools].sort(compareSpoolsForSelect).map((spool) => (
                <option key={spool.id} value={spool.id}>{formatSpoolSelectLabel(spool)}</option>
              ))}
            </select></label>
            <label>Used (g)<input type="number" value={line.used_g} onChange={(e) => updateLine(index, 'used_g', e.target.value)} required /></label>
          </div>
        ))}
        <button type="button" className="secondary" onClick={() => setLines((prev) => [...prev, { spool_id: '', used_g: '', material: '', ams_slot: prev.length + 1 }])}>
          Add filament line
        </button>
        <div className="toolbar">
          <button type="submit">Save print</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
