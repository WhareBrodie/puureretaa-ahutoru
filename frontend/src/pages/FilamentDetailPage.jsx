import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, colorStyle, formatDate, labelDownloadUrl, labelUrl, photoUrl } from '../api';
import FilamentFormModal from '../components/FilamentFormModal';
import SpoolFormModal from '../components/SpoolFormModal';
import SpoolRing from '../components/SpoolRing';
import { formatMoney, formatWeight, parseFilamentKey } from '../utils/filaments';
import { colorSpecLabel } from '../utils/colors';

const LABELGEN_URL = 'https://bambu-labelgen.socuul.dev/';

export default function FilamentDetailPage() {
  const { key } = useParams();
  const navigate = useNavigate();
  const [spools, setSpools] = useState([]);
  const [locations, setLocations] = useState([]);
  const [label, setLabel] = useState(null);
  const [labelBusy, setLabelBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [showFilamentForm, setShowFilamentForm] = useState(false);
  const [editSpool, setEditSpool] = useState(null);
  const [error, setError] = useState('');
  const [labelError, setLabelError] = useState('');
  const fileInputRef = useRef(null);

  const filament = useMemo(() => parseFilamentKey(key), [key]);

  const loadLabel = () => {
    if (!key) return;
    api.filaments
      .getLabel(key)
      .then(setLabel)
      .catch(() => setLabel({ has_label: false }));
  };

  const load = () => {
    Promise.all([api.spools.list(), api.locations.list()])
      .then(([spoolData, locationData]) => {
        setSpools(spoolData.spools || []);
        setLocations(locationData.locations || []);
      })
      .catch((err) => setError(err.message));
    loadLabel();
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
  const displayName = filament.color_name || `${filament.brand} ${filament.material}`;
  const previewUrl = labelUrl(label);
  const downloadUrl = labelDownloadUrl(label);
  const isImageLabel = previewUrl && !previewUrl.toLowerCase().endsWith('.pdf');

  const defaultForm = sample
    ? {
        brand: filament.brand,
        material: filament.material,
        color_name: filament.color_name || '',
        color_hex: sample.color_hex || '#22C55E',
      }
    : null;

  const onPickLabel = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !key) return;
    setLabelBusy(true);
    setLabelError('');
    try {
      const meta = await api.filaments.uploadLabel(key, file);
      setLabel(meta);
    } catch (err) {
      setLabelError(err.message);
    } finally {
      setLabelBusy(false);
    }
  };

  const onDeleteLabel = async () => {
    if (!key || !label?.has_label) return;
    if (!window.confirm('Delete the stored label for this filament?')) return;
    setLabelBusy(true);
    setLabelError('');
    try {
      await api.filaments.deleteLabel(key);
      setLabel({ has_label: false });
    } catch (err) {
      setLabelError(err.message);
    } finally {
      setLabelBusy(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <Link to="/filaments" className="muted back-link">← Back to filaments</Link>
          <h1>{displayName}</h1>
          <p>{filament.brand} · {filament.material}</p>
        </div>
        <div className="page-header-actions">
          <button type="button" className="secondary" onClick={() => setShowFilamentForm(true)}>
            Edit filament
          </button>
          <button type="button" onClick={() => setShowForm(true)}>+ Add spool</button>
        </div>
      </div>

      <div className="filament-hero card">
        <div className="filament-hero-top">
          <div className="filament-hero-brand">
            <strong>{filament.brand}</strong>
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
                {colorSpecLabel(sample.color_hex)}
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

      <div className="card filament-label-card">
        <div className="filament-label-header">
          <div>
            <h2>Label</h2>
            <p className="muted">
              Create a replica at{' '}
              <a href={LABELGEN_URL} target="_blank" rel="noreferrer">
                Bambu LabelGen
              </a>
              , then store the PNG here for re-download later.
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp,.pdf,image/png,image/jpeg,image/webp,application/pdf"
            hidden
            onChange={onPickLabel}
          />
          {!label?.has_label ? (
            <button
              type="button"
              disabled={labelBusy || !matchingSpools.length}
              onClick={() => fileInputRef.current?.click()}
            >
              {labelBusy ? 'Uploading…' : 'Upload label'}
            </button>
          ) : null}
        </div>

        {labelError && <div className="danger" style={{ marginBottom: '0.75rem' }}>{labelError}</div>}

        {label?.has_label ? (
          <div className="filament-label-body">
            {isImageLabel ? (
              <a className="filament-label-preview" href={previewUrl} target="_blank" rel="noreferrer">
                <img src={previewUrl} alt={label.original_filename || 'Filament label'} />
              </a>
            ) : (
              <div className="filament-label-preview filament-label-preview-pdf muted">PDF</div>
            )}
            <div className="filament-label-meta">
              <div>
                <strong>{label.original_filename}</strong>
                <div className="muted">Uploaded {formatDate(label.uploaded_at)}</div>
              </div>
              <div className="filament-label-actions">
                <a className="button secondary" href={downloadUrl} download={label.original_filename || true}>
                  Download
                </a>
                <button
                  type="button"
                  className="secondary"
                  disabled={labelBusy}
                  onClick={() => fileInputRef.current?.click()}
                >
                  Replace
                </button>
                <button
                  type="button"
                  className="secondary danger-text"
                  disabled={labelBusy}
                  onClick={onDeleteLabel}
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        ) : (
          <p className="muted filament-label-empty">
            {matchingSpools.length
              ? 'No label uploaded yet.'
              : 'Add a spool for this filament before uploading a label.'}
          </p>
        )}
      </div>

      <div className="spool-list-section">
        <h2>Spools</h2>
        {!matchingSpools.length ? (
          <p className="muted">No spools for this filament yet.</p>
        ) : (
          <div className="spool-list">
            {matchingSpools.map((spool) => (
                <div key={spool.id} className="card spool-list-item spool-list-item-row">
                  <Link to={`/spools/${spool.id}`} className="spool-list-link">
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
                    </div>
                    <div className="muted spool-list-date">
                      {spool.purchase_price != null && <span>{formatMoney(spool.purchase_price)}</span>}
                      {spool.purchase_date && <span>{spool.purchase_price != null ? ' · ' : ''}{spool.purchase_date}</span>}
                      {!spool.purchase_price && !spool.purchase_date && spool.updated_at && (
                        <span>Updated {formatDate(spool.updated_at)}</span>
                      )}
                    </div>
                  </Link>
                  <button type="button" className="secondary spool-edit-btn" onClick={() => setEditSpool(spool)}>Edit</button>
                </div>
              ))}
          </div>
        )}
      </div>

      {showFilamentForm && (
        <FilamentFormModal
          filamentKey={key}
          filament={{
            brand: filament.brand,
            material: filament.material,
            color_name: filament.color_name,
            color_hex: sample?.color_hex,
          }}
          spoolCount={matchingSpools.length}
          onClose={() => setShowFilamentForm(false)}
          onSaved={(result) => {
            setShowFilamentForm(false);
            if (result.key) {
              navigate(`/filaments/${result.key}`, { replace: true });
            } else {
              load();
            }
          }}
        />
      )}

      {(showForm || editSpool) && (
        <SpoolFormModal
          locations={locations}
          spool={editSpool || defaultForm}
          onClose={() => {
            setShowForm(false);
            setEditSpool(null);
          }}
          onSaved={() => {
            setShowForm(false);
            setEditSpool(null);
            load();
          }}
        />
      )}
    </>
  );
}
