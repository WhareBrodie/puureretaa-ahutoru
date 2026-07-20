import { useState } from 'react';
import { api } from '../api';
import ColorPickerField from './ColorPickerField';

export default function FilamentFormModal({ filamentKey, filament, spoolCount, onClose, onSaved }) {
  const [form, setForm] = useState({
    brand: filament.brand || '',
    material: filament.material || '',
    color_name: filament.color_name || '',
    color_hex: filament.color_hex || '#22C55E',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const result = await api.filaments.update(filamentKey, {
        brand: form.brand.trim(),
        material: form.material.trim(),
        color_name: form.color_name.trim() || null,
        color_hex: form.color_hex || null,
      });
      onSaved(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Edit filament</h2>
        <p className="muted">
          Updates brand, material, colour name, and swatch for all {spoolCount} spool
          {spoolCount === 1 ? '' : 's'} in this filament type.
        </p>
        {error && <div className="danger">{error}</div>}
        <div className="form-grid two">
          <label>
            Brand
            <input value={form.brand} onChange={(e) => update('brand', e.target.value)} required />
          </label>
          <label>
            Material
            <input value={form.material} onChange={(e) => update('material', e.target.value)} required />
          </label>
          <label className="full-width">
            Color name
            <input value={form.color_name} onChange={(e) => update('color_name', e.target.value)} />
          </label>
        </div>
        <ColorPickerField value={form.color_hex} onChange={(value) => update('color_hex', value)} />
        <div className="toolbar">
          <button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save filament'}</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>
  );
}
