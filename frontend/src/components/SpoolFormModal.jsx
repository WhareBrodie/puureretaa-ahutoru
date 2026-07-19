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
  empty_spool_weight_g: '',
  notes: '',
  low_stock_threshold_g: 100,
};

export default function SpoolFormModal({ locations, spool, onClose, onSaved }) {
  const [form, setForm] = useState(spool?.id ? spool : { ...emptyForm, ...spool });
  const [emptyWeights, setEmptyWeights] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    if (form.brand) {
      api.emptySpoolWeights(form.brand)
        .then((data) => setEmptyWeights(data.entries || []))
        .catch(() => setEmptyWeights([]));
    }
  }, [form.brand]);

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

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
          <label>
            Empty spool weight (g)
            <input
              type="number"
              value={form.empty_spool_weight_g}
              onChange={(e) => update('empty_spool_weight_g', e.target.value)}
              list="empty-spool-weights"
            />
          </label>
          <datalist id="empty-spool-weights">
            {emptyWeights.map((entry) => (
              <option key={entry.id} value={entry.weight_g}>{entry.brand} {entry.model}</option>
            ))}
          </datalist>
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
