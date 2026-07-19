import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, photoUrl } from '../api';
import SpoolRing from '../components/SpoolRing';
import { formatWeight, groupSpoolsByLocation, isDepleted } from '../utils/filaments';

export default function InventoryPage() {
  const [spools, setSpools] = useState([]);
  const [locations, setLocations] = useState([]);
  const [showDepleted, setShowDepleted] = useState(false);
  const [error, setError] = useState('');
  const sectionRefs = useRef({});

  useEffect(() => {
    Promise.all([api.spools.list(), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpools(spoolData.spools || []);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
  }, []);

  const locationGroups = useMemo(() => {
    const filtered = showDepleted ? spools : spools.filter((s) => !isDepleted(s));
    return groupSpoolsByLocation(filtered, locations);
  }, [spools, locations, showDepleted]);

  const scrollToLocation = (locId) => {
    const id = locId ?? 'unassigned';
    sectionRefs.current[id]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  if (error) return <div className="card danger">{error}</div>;

  return (
    <div className="inventory-layout">
      <div className="inventory-main">
        <div className="page-header">
          <div>
            <h1>Inventory</h1>
            <p>Find any spool by storage location</p>
          </div>
          <label className="toggle-label">
            <input type="checkbox" checked={showDepleted} onChange={(e) => setShowDepleted(e.target.checked)} />
            Show depleted
          </label>
        </div>

        {locationGroups.map(({ location, spools: locSpools }) => {
          const sectionId = location.id ?? 'unassigned';
          return (
            <section
              key={sectionId}
              className="location-section"
              ref={(el) => { sectionRefs.current[sectionId] = el; }}
            >
              <div className="location-header">
                <span className="location-icon">📦</span>
                <h2>{location.name}</h2>
                <span className="muted">{locSpools.length} spool{locSpools.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="inventory-spool-grid">
                {locSpools.map((spool) => {
                  const photo = photoUrl(spool);
                  return (
                    <Link key={spool.id} to={`/spools/${spool.id}`} className="inventory-spool-card">
                      {photo ? (
                        <div className="inventory-spool-photo" style={{ backgroundImage: `url(${photo})` }} />
                      ) : (
                        <SpoolRing
                          remaining={spool.remaining_g || 0}
                          capacity={spool.initial_weight_g || 1000}
                          colorHex={spool.color_hex}
                          size={56}
                        />
                      )}
                      <div className="inventory-spool-brand">{spool.brand}</div>
                      <div className="inventory-spool-name">{spool.color_name || spool.material}</div>
                      <div className="inventory-spool-material">{spool.material}</div>
                      <div className="inventory-spool-weight muted">{formatWeight(spool.remaining_g)}</div>
                      {spool.qr_code_id && (
                        <div className="inventory-spool-id">{spool.qr_code_id.slice(0, 8)}</div>
                      )}
                    </Link>
                  );
                })}
              </div>
            </section>
          );
        })}

        {!locationGroups.length && (
          <div className="card muted empty-state">No spools in inventory yet. Add spools with storage locations to see them here.</div>
        )}
      </div>

      <aside className="inventory-nav">
        <div className="inventory-nav-title">Locations</div>
        {locationGroups.map(({ location, spools: locSpools }) => (
          <button
            key={location.id ?? 'unassigned'}
            type="button"
            className="inventory-nav-btn"
            onClick={() => scrollToLocation(location.id)}
          >
            {location.name}
            <span className="muted">{locSpools.length}</span>
          </button>
        ))}
      </aside>
    </div>
  );
}
