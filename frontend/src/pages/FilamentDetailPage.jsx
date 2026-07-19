import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, colorStyle, formatDate, photoUrl } from '../api';
import SpoolFormModal from '../components/SpoolFormModal';
import SpoolRing from '../components/SpoolRing';
import Stars from '../components/Stars';
import { formatWeight, parseFilamentKey } from '../utils/filaments';

export default function FilamentDetailPage() {
  const { key } = useParams();
  const [spools, setSpools] = useState([]);
  const [locations, setLocations] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState('');

  const filament = useMemo(() => parseFilamentKey(key), [key]);

  const load = () => {
    Promise.all([api.spools.list(), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpools(spoolData.spools || []);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, [key]);

  const matchingSpools = useMemo(
    () =>
      spools
        .filter(
          (s) =>
            s.brand === filament.brand &&
            s.material === filament.material &&
            (s.color_name || '') === (filament.color_name || ''),
        )
        .sort((a, b) => (b.remaining_g || 0) - (a.remaining_g || 0)),
    [spools, filament],
  );

  if (error) return <div className="card danger">{error}</div>;

  const totalRemaining = matchingSpools.reduce((sum, s) => sum + (s.remaining_g || 0), 0);
  const totalCapacity = matchingSpools.reduce((sum, s) => sum + (s.initial_weight_g || 1000), 0);
  const pct = totalCapacity ? Math.round((totalRemaining / totalCapacity) * 100) : 0;
  const sample = matchingSpools[0];
  const photo = sample ? photoUrl(sample) : null;
  const rating = matchingSpools.reduce((best, s) => Math.max(best, s.rating || 0), 0) || null;
  const displayName = filament.color_name || `${filament.brand} ${filament.material}`;

  const defaultForm = sample
    ? {
        brand: filament.brand,
        material: filament.material,
        color_name: filament.color_name || '',
        color_hex: sample.color_hex || '#22C55E',
      }
    : null;

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/filaments" className="muted back-link">← Back to filaments</Link>
          <h1>{displayName}</h1>
          <p>{filament.brand} · {filament.material}</p>
        </div>
        <button onClick={() => setShowForm(true)}>+ Add spool</button>
      </div>

      <div className="filament-hero card">
        <div className="filament-hero-top">
          <div className="filament-hero-brand">
            <strong>{filament.brand}</strong>
            <Stars rating={rating} />
          </div>
          <span className="badge material">{filament.material}</span>
        </div>

        <div className="filament-hero-body">
          {photo ? (
            <div className="filament-hero-photo" style={{ backgroundImage: `url(${photo})` }} />
          ) : (
            <SpoolRing
              remaining={totalRemaining}
              capacity={totalCapacity}
              colorHex={sample?.color_hex}
              size={72}
            />
          )}
          <div className="filament-hero-stats">
            <div>
              <div className="stat-label">Active spools</div>
              <div className="stat-value">{matchingSpools.length}</div>
            </div>
            {sample?.color_hex && (
              <div className="color-chip">
                <span className="color-dot" style={colorStyle(sample.color_hex)} />
                {sample.color_hex}
              </div>
            )}
          </div>
        </div>

        <div className="capacity-bar">
          <div className="capacity-bar-label">
            Remaining: <strong>{formatWeight(totalRemaining)}</strong> / {formatWeight(totalCapacity)} · {pct}%
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{ width: `${pct}%`, ...(sample?.color_hex ? colorStyle(sample.color_hex) : {}) }}
            />
          </div>
        </div>
      </div>

      <div className="spool-list-section">
        <h2>Spools</h2>
        {!matchingSpools.length ? (
          <p className="muted">No spools for this filament yet.</p>
        ) : (
          <div className="spool-list">
            {matchingSpools.map((spool) => {
              const low = (spool.remaining_g || 0) <= (spool.low_stock_threshold_g || 100);
              return (
                <Link key={spool.id} to={`/spools/${spool.id}`} className="card spool-list-item">
                  <SpoolRing
                    remaining={spool.remaining_g || 0}
                    capacity={spool.initial_weight_g || 1000}
                    colorHex={spool.color_hex}
                  />
                  <div className="spool-list-weight">
                    <strong>{formatWeight(spool.remaining_g)}</strong>
                    <span className="muted"> / {formatWeight(spool.initial_weight_g || 1000)}</span>
                  </div>
                  <div className="spool-list-meta">
                    {spool.location_name && (
                      <span className="badge location">📍 {spool.location_name}</span>
                    )}
                    {spool.qr_code_id && <span className="muted spool-id">{spool.qr_code_id.slice(0, 8)}</span>}
                    {low && <span className="badge warning">Low</span>}
                  </div>
                  <div className="muted spool-list-date">
                    {spool.updated_at ? `Updated ${formatDate(spool.updated_at)}` : ''}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {showForm && (
        <SpoolFormModal
          locations={locations}
          spool={defaultForm}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            load();
          }}
        />
      )}
    </>
  );
}
