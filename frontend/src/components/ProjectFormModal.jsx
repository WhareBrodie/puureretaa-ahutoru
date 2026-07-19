import { useState } from 'react';
import { api } from '../api';

export default function ProjectFormModal({ project, onClose, onSaved }) {
  const [name, setName] = useState(project?.name || '');
  const [notes, setNotes] = useState(project?.notes || '');
  const [error, setError] = useState('');

  const submit = async (event) => {
    event.preventDefault();
    try {
      const body = { name, notes: notes || null };
      if (project?.id) {
        await api.projects.update(project.id, body);
      } else {
        await api.projects.create(body);
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{project?.id ? 'Edit project' : 'New project'}</h2>
        {error && <div className="danger">{error}</div>}
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Notes
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>
        <div className="toolbar">
          <button type="submit">Save project</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
