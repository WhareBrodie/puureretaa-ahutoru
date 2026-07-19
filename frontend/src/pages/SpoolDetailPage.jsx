import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, colorStyle, daysSince, formatDate, photoUrl } from '../api';
import SpoolFormModal from '../components/SpoolFormModal';
import { formatMoney, usageCost } from '../utils/filaments';

export default function SpoolDetailPage() {
  const { id } = useParams();
  const [spool, setSpool] = useState(null);
  const [locations, setLocations] = useState([]);
  const [scaleWeight, setScaleWeight] = useState('');
  const [dryingNotes, setDryingNotes] = useState('');
  const [showEdit, setShowEdit] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([api.spools.get(id), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpool(spoolData);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, [id]);

  const handlePhoto = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      await api.spools.uploadPhoto(id, file);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleScale = async () => {
    try {
      await api.spools.calculateWeight(id, Number(scaleWeight));
      setScaleWeight('');
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDrying = async () => {
    try {
      await api.spools.addDryingLog(id, { notes: dryingNotes });
      setDryingNotes('');
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  if (error) return <div className="card danger">{error}</div>;
  if (!spool) return <div className="card muted">Loading spool…</div>;

  const photo = photoUrl(spool);
  const driedDays = daysSince(spool.last_dried_at);
  const emptyWeight = Number(spool.empty_spool_weight_g || 0);
  const totalWeight = Number(scaleWeight);
  const previewFilament = totalWeight > 0 && emptyWeight > 0
    ? Math.max(0, totalWeight - emptyWeight)
    : null;
  const emptyLabel = spool.empty_spool_brand
    ? `${spool.empty_spool_brand}${spool.empty_spool_model ? ` · ${spool.empty_spool_model}` : ''}`
    : null;
  const costPerGram = spool.purchase_price && spool.initial_weight_g
    ? spool.purchase_price / spool.initial_weight_g
    : null;

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/filaments" className="muted back-link">← Back to filaments</Link>
          <h1>{spool.color_name || `${spool.brand} ${spool.material}`}</h1>
          <p>{spool.brand} · {spool.material} · {Math.round(spool.remaining_g || 0)}g remaining</p>
        </div>
        <button onClick={() => setShowEdit(true)}>Edit spool</button>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="swatch" style={{ height: 180, borderRadius: '0.75rem', ...(photo ? { backgroundImage: `url(${photo})`, backgroundSize: 'cover' } : colorStyle(spool.color_hex)) }} />
          <div style={{ marginTop: '1rem' }}>
            <label>
              Upload photo
              <input type="file" accept="image/*" onChange={handlePhoto} />
            </label>
          </div>
          <div className="form-grid two" style={{ marginTop: '1rem' }}>
            <div><strong>Purchase price</strong><div>{spool.purchase_price != null ? formatMoney(spool.purchase_price) : '—'}</div></div>
            <div><strong>Cost per gram</strong><div>{costPerGram != null ? `$${costPerGram.toFixed(4)}` : '—'}</div></div>
            <div><strong>Purchase date</strong><div>{spool.purchase_date || '—'}</div></div>
            <div><strong>Supplier</strong><div>{spool.supplier || '—'}</div></div>
            <div><strong>Batch</strong><div>{spool.batch_number || '—'}</div></div>
            <div><strong>Location</strong><div>{spool.location_name || '—'}</div></div>
            <div><strong>Empty spool</strong><div>{emptyLabel ? `${emptyLabel} (${emptyWeight || '—'}g)` : (emptyWeight ? `${emptyWeight}g` : '—')}</div></div>
            <div><strong>Last weighed</strong><div>{spool.last_weighed_at ? formatDate(spool.last_weighed_at) : 'Never'}</div></div>
            <div><strong>Last dried</strong><div>{spool.last_dried_at ? `${formatDate(spool.last_dried_at)} (${driedDays}d ago)` : 'Never logged'}</div></div>
          </div>
        </div>

        <div className="grid">
          <div className="card">
            <h2>Weigh spool</h2>
            <p className="muted">
              Put the spool on the scale and enter the total weight. Filament remaining = total − empty spool
              {emptyWeight ? ` (${emptyWeight}g)` : ''}.
            </p>
            <div className="toolbar">
              <input value={scaleWeight} onChange={(e) => setScaleWeight(e.target.value)} placeholder="Total on scale (g)" />
              <button onClick={handleScale}>Update from scale</button>
            </div>
            {previewFilament != null && (
              <p className="muted">
                Preview: {totalWeight}g total − {emptyWeight}g spool = <strong>{Math.round(previewFilament)}g</strong> filament
              </p>
            )}
          </div>

          <div className="card">
            <h2>Log drying</h2>
            <label>
              Notes
              <textarea rows={3} value={dryingNotes} onChange={(e) => setDryingNotes(e.target.value)} />
            </label>
            <button onClick={handleDrying} style={{ marginTop: '0.75rem' }}>Add drying entry</button>
          </div>

          <div className="card">
            <h2>Usage history</h2>
            {spool.usage_history?.length ? (
              <table className="table">
                <thead>
                  <tr><th>Print</th><th>Used</th><th>Cost</th><th>When</th></tr>
                </thead>
                <tbody>
                  {spool.usage_history.map((usage) => {
                    const cost = usage.cost ?? usageCost(
                      usage.used_g,
                      spool.purchase_price,
                      spool.initial_weight_g,
                    );
                    return (
                      <tr key={usage.id}>
                        <td>{usage.title}</td>
                        <td>{Math.round(usage.used_g || 0)}g</td>
                        <td>{cost != null ? formatMoney(cost) : '—'}</td>
                        <td>{formatDate(usage.started_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted">No usage recorded yet.</p>
            )}
          </div>
        </div>
      </div>

      {showEdit && (
        <SpoolFormModal
          locations={locations}
          spool={spool}
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
