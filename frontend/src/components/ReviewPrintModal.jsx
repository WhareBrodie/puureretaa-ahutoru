import { useState } from 'react';
import { api } from '../api';
import { formatUsageG } from '../utils/filaments';

export default function ReviewPrintModal({ printJob, spools, onClose, onSaved }) {
  const [assignments, setAssignments] = useState(
    (printJob.usages || []).map((usage) => ({ usage_id: usage.id, spool_id: usage.spool_id || '' })),
  );
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  const updateAssignment = (usageId, spoolId) => {
    setAssignments((prev) => prev.map((item) => (item.usage_id === usageId ? { ...item, spool_id: spoolId } : item)));
  };

  const submit = async (event) => {
    event.preventDefault();
    try {
      await api.prints.review(printJob.id, {
        assignments: assignments.map((item) => ({
          usage_id: item.usage_id,
          spool_id: item.spool_id ? Number(item.spool_id) : null,
        })),
        review_note: note,
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Review print</h2>
        <p className="muted">{printJob.title} — assign a spool for each AMS slot usage.</p>
        {error && <div className="danger">{error}</div>}
        {(printJob.usages || []).map((usage) => (
          <div key={usage.id} className="card" style={{ background: 'var(--panel-2)' }}>
            <strong>Slot {usage.ams_slot || '?'}</strong>
            <div className="muted">{usage.material} {usage.color || ''} — {formatUsageG(usage.used_g)}</div>
            <label>
              Assign spool
              <select
                value={assignments.find((item) => item.usage_id === usage.id)?.spool_id || ''}
                onChange={(e) => updateAssignment(usage.id, e.target.value)}
              >
                <option value="">Choose spool</option>
                {spools
                  .filter((spool) => !usage.material || spool.material === usage.material)
                  .map((spool) => (
                    <option key={spool.id} value={spool.id}>
                      {spool.brand} {spool.material} {spool.color_name || ''} ({Math.round(spool.remaining_g || 0)}g)
                    </option>
                  ))}
              </select>
            </label>
          </div>
        ))}
        <label>Review note<textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <div className="toolbar">
          <button type="submit">Apply deductions</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
