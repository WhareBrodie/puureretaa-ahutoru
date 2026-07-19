import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, colorStyle, photoUrl } from '../api';
import SpoolFormModal from '../components/SpoolFormModal';

function Stars({ rating }) {
  if (!rating) return <span className="muted">Unrated</span>;
  return <span className="stars">{'★'.repeat(rating)}{'☆'.repeat(5 - rating)}</span>;
}

export default function SpoolsPage() {
  const [spools, setSpools] = useState([]);
  const [locations, setLocations] = useState([]);
  const [material, setMaterial] = useState('');
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    const params = {};
    if (material) params.material = material;
    if (lowStockOnly) params.low_stock = 'true';
    Promise.all([api.spools.list(params), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpools(spoolData.spools || []);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, [material, lowStockOnly]);

  const materials = [...new Set(spools.map((s) => s.material))].sort();

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Spools</h1>
          <p>Inventory with colors, ratings, and remaining weight</p>
        </div>
        <button onClick={() => setShowForm(true)}>Add spool</button>
      </div>

      <div className="toolbar card">
        <select value={material} onChange={(e) => setMaterial(e.target.value)}>
          <option value="">All materials</option>
          {materials.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', width: 'auto' }}>
          <input type="checkbox" checked={lowStockOnly} onChange={(e) => setLowStockOnly(e.target.checked)} />
          Low stock only
        </label>
      </div>

      {error && <div className="card danger">{error}</div>}

      <div className="spool-grid" style={{ marginTop: '1rem' }}>
        {spools.map((spool) => {
          const photo = photoUrl(spool);
          const low = (spool.remaining_g || 0) <= (spool.low_stock_threshold_g || 100);
          return (
            <Link key={spool.id} to={`/spools/${spool.id}`} className="card spool-card" style={{ textDecoration: 'none', color: 'inherit' }}>
              <div className="swatch" style={photo ? { backgroundImage: `url(${photo})`, backgroundSize: 'cover', backgroundPosition: 'center' } : colorStyle(spool.color_hex)} />
              <div className="spool-card-body">
                <h3>{spool.color_name || spool.material}</h3>
                <div className="muted">{spool.brand} · {spool.material}</div>
                <div>{Math.round(spool.remaining_g || 0)}g remaining</div>
                <Stars rating={spool.rating} />
                {low && <div className="badge warning" style={{ marginTop: '0.5rem' }}>Low stock</div>}
              </div>
            </Link>
          );
        })}
      </div>

      {showForm && (
        <SpoolFormModal
          locations={locations}
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
