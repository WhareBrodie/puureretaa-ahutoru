import { useState } from 'react';
import { api } from '../api';

export default function MoveSpoolModal({ spool, locations, onClose, onSaved }) {
  const [locationId, setLocationId] = useState(spool.location_id ?? '');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.spools.update(spool.id, {
        location_id: locationId ? Number(locationId) : null,
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const label = spool.color_name || `${spool.brand} ${spool.material}`;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Move spool</h2>
        <p className="muted">{label}</p>
        {error && <div className="danger">{error}</div>}
        <label>
          Storage location
          <select value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            <option value="">Unassigned</option>
            {locations.map((location) => (
              <option key={location.id} value={location.id}>{location.name}</option>
            ))}
          </select>
        </label>
        <div className="toolbar">
          <button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Move'}</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
