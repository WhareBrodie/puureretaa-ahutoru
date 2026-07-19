import { useEffect, useState } from 'react';
import { api } from '../api';
import ColorPickerField from './ColorPickerField';

const emptyForm = {
  brand: 'Bambu Lab',
  material: 'PLA',
  color_name: '',
  color_hex: '#22C55E',
  purchase_price: '',
  purchase_date: '',
  supplier: '',
  batch_number: '',
  location_id: '',
  remaining_g: 1000,
  initial_weight_g: 1000,
  empty_spool_weight_id: '',
  empty_spool_weight_g: '',
  notes: '',
  low_stock_threshold_g: 100,
};

function profileLabel(entry) {
  return `${entry.brand}${entry.model ? ` · ${entry.model}` : ''} (${entry.weight_g}g)`;
}

export default function SpoolFormModal({ locations, spool, onClose, onSaved }) {
  const [form, setForm] = useState(spool?.id ? spool : { ...emptyForm, ...spool });
  const [profiles, setProfiles] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    api.emptySpoolProfiles.list()
      .then(setProfiles)
      .catch(() => setProfiles([]));
  }, []);

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const brandProfiles = profiles.filter(
    (entry) => entry.brand === form.brand || entry.brand === 'Generic',
  );
  const otherProfiles = profiles.filter(
    (entry) => entry.brand !== form.brand && entry.brand !== 'Generic',
  );

  const selectProfile = (profileId) => {
    if (!profileId) {
      update('empty_spool_weight_id', '');
      return;
    }
    const entry = profiles.find((item) => String(item.id) === String(profileId));
    if (!entry) return;
    setForm((prev) => ({
      ...prev,
      empty_spool_weight_id: entry.id,
      empty_spool_weight_g: entry.weight_g,
    }));
  };

  const submit = async (event) => {
    event.preventDefault();
    try {
      const payload = {
        ...form,
        purchase_price: form.purchase_price ? Number(form.purchase_price) : null,
        purchase_date: form.purchase_date || null,
        location_id: form.location_id ? Number(form.location_id) : null,
        remaining_g: Number(form.remaining_g),
        initial_weight_g: Number(form.initial_weight_g),
        empty_spool_weight_id: form.empty_spool_weight_id ? Number(form.empty_spool_weight_id) : null,
        empty_spool_weight_g: form.empty_spool_weight_g ? Number(form.empty_spool_weight_g) : null,
        low_stock_threshold_g: Number(form.low_stock_threshold_g || 100),
      };
      if (spool?.id) {
        await api.spools.update(spool.id, payload);
      } else {
        await api.spools.create(payload);
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{spool?.id ? 'Edit spool' : 'Add spool'}</h2>
        {error && <div className="danger">{error}</div>}
        <div className="form-grid two">
          <label>Brand<input value={form.brand} onChange={(e) => update('brand', e.target.value)} required /></label>
          <label>Material<input value={form.material} onChange={(e) => update('material', e.target.value)} required /></label>
          <label>Color name<input value={form.color_name} onChange={(e) => update('color_name', e.target.value)} /></label>
        </div>
        <ColorPickerField value={form.color_hex} onChange={(value) => update('color_hex', value)} />
        <div className="form-grid two">
          <label>Remaining (g)<input type="number" value={form.remaining_g} onChange={(e) => update('remaining_g', e.target.value)} /></label>
          <label>Initial (g)<input type="number" value={form.initial_weight_g} onChange={(e) => update('initial_weight_g', e.target.value)} /></label>
          <label className="full-width">
            Empty spool type
            <select
              value={form.empty_spool_weight_id || ''}
              onChange={(e) => selectProfile(e.target.value)}
            >
              <option value="">Select empty spool profile…</option>
              {brandProfiles.map((entry) => (
                <option key={entry.id} value={entry.id}>{profileLabel(entry)}</option>
              ))}
              {otherProfiles.length > 0 && (
                <optgroup label="Other brands">
                  {otherProfiles.map((entry) => (
                    <option key={entry.id} value={entry.id}>{profileLabel(entry)}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          <label>
            Or custom empty weight (g)
            <input
              type="number"
              value={form.empty_spool_weight_g}
              onChange={(e) => {
                update('empty_spool_weight_g', e.target.value);
                update('empty_spool_weight_id', '');
              }}
              placeholder="e.g. 238"
            />
          </label>
          <label>Purchase price ($)<input type="number" step="0.01" min="0" value={form.purchase_price} onChange={(e) => update('purchase_price', e.target.value)} placeholder="e.g. 24.99" /></label>
          <label>Purchase date<input type="date" value={form.purchase_date || ''} onChange={(e) => update('purchase_date', e.target.value)} /></label>
          <label>Location<select value={form.location_id || ''} onChange={(e) => update('location_id', e.target.value)}>
            <option value="">None</option>
            {locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
          </select></label>
        </div>
        <label>Notes<textarea rows={3} value={form.notes || ''} onChange={(e) => update('notes', e.target.value)} /></label>
        <div className="toolbar">
          <button type="submit">Save spool</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
