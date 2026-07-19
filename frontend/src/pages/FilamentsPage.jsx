import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, colorStyle, photoUrl } from '../api';
import SpoolFormModal from '../components/SpoolFormModal';
import SpoolRing from '../components/SpoolRing';
import Stars from '../components/Stars';
import { formatWeight, groupSpoolsIntoFilaments } from '../utils/filaments';

export default function FilamentsPage() {
  const [spools, setSpools] = useState([]);
  const [locations, setLocations] = useState([]);
  const [search, setSearch] = useState('');
  const [material, setMaterial] = useState('');
  const [showDepleted, setShowDepleted] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([api.spools.list(), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpools(spoolData.spools || []);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, []);

  const materials = useMemo(
    () => [...new Set(spools.map((s) => s.material))].sort(),
    [spools],
  );

  const filaments = useMemo(() => {
    let groups = groupSpoolsIntoFilaments(spools, { includeDepleted: showDepleted });
    if (material) groups = groups.filter((f) => f.material === material);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      groups = groups.filter(
        (f) =>
          (f.color_name || '').toLowerCase().includes(q) ||
          f.brand.toLowerCase().includes(q) ||
          f.material.toLowerCase().includes(q),
      );
    }
    return groups;
  }, [spools, material, search, showDepleted]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Filaments</h1>
          <p>One row per filament type — click to see individual spools</p>
        </div>
        <button className="fab" onClick={() => setShowForm(true)} title="Add spool">+</button>
      </div>

      <div className="toolbar card">
        <input
          className="search-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search filaments…"
        />
        <select value={material} onChange={(e) => setMaterial(e.target.value)}>
          <option value="">All materials</option>
          {materials.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
        <label className="toggle-label">
          <input type="checkbox" checked={showDepleted} onChange={(e) => setShowDepleted(e.target.checked)} />
          Show depleted spools
        </label>
      </div>

      {error && <div className="card danger">{error}</div>}

      <div className="filament-table-wrap card">
        <table className="filament-table">
          <thead>
            <tr>
              <th aria-label="Color" />
              <th>Name</th>
              <th>Brand</th>
              <th>Material</th>
              <th>Spools</th>
              <th>Rating</th>
              <th aria-label="Alerts" />
            </tr>
          </thead>
          <tbody>
            {filaments.map((filament) => {
              const photo = photoUrl(filament);
              const pct = filament.total_capacity_g
                ? filament.total_remaining_g / filament.total_capacity_g
                : 0;
              return (
                <tr key={filament.key}>
                  <td>
                    <Link to={`/filaments/${filament.key}`} className="filament-link">
                      {photo ? (
                        <div
                          className="filament-swatch photo"
                          style={{ backgroundImage: `url(${photo})` }}
                        />
                      ) : (
                        <SpoolRing
                          remaining={filament.total_remaining_g}
                          capacity={filament.total_capacity_g}
                          colorHex={filament.color_hex}
                        />
                      )}
                    </Link>
                  </td>
                  <td>
                    <Link to={`/filaments/${filament.key}`} className="filament-link">
                      <strong>{filament.color_name || `${filament.brand} ${filament.material}`}</strong>
                      {filament.updated_at && (
                        <div className="muted filament-updated">
                          Updated {new Date(filament.updated_at).toLocaleDateString()}
                        </div>
                      )}
                    </Link>
                  </td>
                  <td>{filament.brand}</td>
                  <td><span className="badge material">{filament.material}</span></td>
                  <td>
                    <span className="badge spool-count">
                      {filament.spool_count} ({formatWeight(filament.total_remaining_g)})
                    </span>
                    <div className="mini-bar" aria-hidden>
                      <div className="mini-bar-fill" style={{ width: `${Math.round(pct * 100)}%`, ...colorStyle(filament.color_hex) }} />
                    </div>
                  </td>
                  <td><Stars rating={filament.rating} /></td>
                  <td>{filament.has_low_stock && <span className="alert-icon" title="Low stock">⚠</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!filaments.length && <p className="muted empty-state">No filaments match your filters.</p>}
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
