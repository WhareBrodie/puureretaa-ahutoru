import { useEffect, useState } from 'react';
import { api, formatDate } from '../api';

const TABS = [
  { id: 'general', label: 'General' },
  { id: 'inventory', label: 'Inventory' },
  { id: 'printer', label: 'Printer' },
  { id: 'data', label: 'Data' },
  { id: 'advanced', label: 'Advanced' },
];

const emptyProfileForm = { brand: 'Bambu Lab', model: '', weight_g: 238, notes: '' };

export default function SettingsPage() {
  const [tab, setTab] = useState('general');
  const [settings, setSettings] = useState(null);
  const [locations, setLocations] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [locationForm, setLocationForm] = useState({ name: '', description: '' });
  const [profileForm, setProfileForm] = useState(emptyProfileForm);
  const [csvText, setCsvText] = useState('');
  const [skipDepleted, setSkipDepleted] = useState(true);
  const [importResult, setImportResult] = useState(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([
      api.settings.get(),
      api.locations.list(),
      api.emptySpoolProfiles.list(),
    ])
      .then(([settingsData, locationData, profileData]) => {
        setSettings(settingsData);
        setLocations(locationData.locations || []);
        setProfiles(profileData || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, []);

  const saveSettings = async () => {
    try {
      const updated = await api.settings.update({
        default_low_stock_threshold_g: Number(settings.default_low_stock_threshold_g),
        drying_alert_days: Number(settings.drying_alert_days),
        material_low_stock_thresholds: settings.material_low_stock_thresholds,
        printer: settings.printer,
      });
      setSettings(updated);
      setMessage('Settings saved');
    } catch (err) {
      setError(err.message);
    }
  };

  const addLocation = async () => {
    try {
      await api.locations.create(locationForm);
      setLocationForm({ name: '', description: '' });
      load();
      setMessage('Location added');
    } catch (err) {
      setError(err.message);
    }
  };

  const addProfile = async () => {
    try {
      await api.emptySpoolProfiles.create({
        ...profileForm,
        weight_g: Number(profileForm.weight_g),
      });
      setProfileForm(emptyProfileForm);
      load();
      setMessage('Empty spool profile added');
    } catch (err) {
      setError(err.message);
    }
  };

  const removeProfile = async (id) => {
    if (!window.confirm('Delete this empty spool profile? Spools using it keep their stored weight.')) return;
    try {
      await api.emptySpoolProfiles.remove(id);
      load();
      setMessage('Profile removed');
    } catch (err) {
      setError(err.message);
    }
  };

  const exportCsv = async () => {
    const csv = await api.exportCsv();
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'spools.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const importCsv = async () => {
    try {
      const result = await api.importCsv(csvText, false, skipDepleted);
      setImportResult(result);
      load();
      setMessage('CSV import finished');
    } catch (err) {
      setError(err.message);
    }
  };

  const importCsvFile = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setCsvText(text);
      const result = await api.importCsv(text, false, skipDepleted);
      setImportResult(result);
      load();
      setMessage('CSV import finished');
    } catch (err) {
      setError(err.message);
    } finally {
      event.target.value = '';
    }
  };

  const skipCloudHistory = async () => {
    if (
      !window.confirm(
        'Clear all Bambu auto-imported prints, restore spool weights those prints deducted, and block that history from coming back on redeploy? Manual print logs are kept.',
      )
    ) {
      return;
    }
    try {
      const updated = await api.settings.skipCloudHistory(true);
      setSettings(updated);
      const parts = [`Removed ${updated.deleted_imported_prints || 0} auto-imported print(s).`];
      if (updated.restored_spools) {
        parts.push(`Restored ${Math.round(updated.restored_grams || 0)}g across ${updated.restored_spools} spool(s).`);
      }
      if (updated.ignored_tasks) {
        parts.push(`Blocked ${updated.ignored_tasks} Bambu task(s) from re-import.`);
      }
      parts.push('Only new prints from now on will sync.');
      setMessage(parts.join(' '));
    } catch (err) {
      setError(err.message);
    }
  };

  if (!settings) return <div className="card muted">Loading settings…</div>;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Alerts, empty spool profiles, printer sync, and backups</p>
        </div>
      </div>

      {error && <div className="card danger">{error}</div>}
      {message && <div className="card">{message}</div>}

      <div className="settings-tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? 'active' : 'secondary'}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'general' && (
        <div className="card form-grid settings-panel">
          <h2>Alerts</h2>
          <div className="form-grid two">
            <label>
              Default low-stock threshold (g)
              <input
                type="number"
                value={settings.default_low_stock_threshold_g}
                onChange={(e) => setSettings({ ...settings, default_low_stock_threshold_g: e.target.value })}
              />
            </label>
            <label>
              Drying alert after (days)
              <input
                type="number"
                value={settings.drying_alert_days}
                onChange={(e) => setSettings({ ...settings, drying_alert_days: e.target.value })}
              />
            </label>
          </div>
          <button onClick={saveSettings}>Save alerts</button>
        </div>
      )}

      {tab === 'inventory' && (
        <div className="grid grid-2">
          <div className="card form-grid settings-panel">
            <h2>Empty spool profiles</h2>
            <p className="muted">
              Define how much an empty spool weighs. Assign a profile to each spool so scale weigh-ins
              subtract the right tare (e.g. 538g total − 238g spool = 300g filament).
            </p>
            <table className="data-table">
              <thead>
                <tr><th>Brand</th><th>Model</th><th>Weight</th><th /></tr>
              </thead>
              <tbody>
                {profiles.map((profile) => (
                  <tr key={profile.id}>
                    <td>{profile.brand}</td>
                    <td>{profile.model || '—'}</td>
                    <td>{profile.weight_g}g</td>
                    <td>
                      <button type="button" className="secondary" onClick={() => removeProfile(profile.id)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="form-grid two">
              <label>Brand<input value={profileForm.brand} onChange={(e) => setProfileForm({ ...profileForm, brand: e.target.value })} /></label>
              <label>Model<input value={profileForm.model} onChange={(e) => setProfileForm({ ...profileForm, model: e.target.value })} placeholder="Plastic spool" /></label>
              <label>Empty weight (g)<input type="number" value={profileForm.weight_g} onChange={(e) => setProfileForm({ ...profileForm, weight_g: e.target.value })} /></label>
              <label>Notes<input value={profileForm.notes} onChange={(e) => setProfileForm({ ...profileForm, notes: e.target.value })} /></label>
            </div>
            <button type="button" className="secondary" onClick={addProfile}>Add profile</button>
          </div>

          <div className="card form-grid settings-panel">
            <h2>Storage locations</h2>
            <ul className="plain-list">
              {locations.map((location) => (
                <li key={location.id}>{location.name}{location.description ? ` — ${location.description}` : ''}</li>
              ))}
            </ul>
            <label>
              New location name
              <input value={locationForm.name} onChange={(e) => setLocationForm({ ...locationForm, name: e.target.value })} />
            </label>
            <label>
              Description
              <input value={locationForm.description} onChange={(e) => setLocationForm({ ...locationForm, description: e.target.value })} />
            </label>
            <button type="button" className="secondary" onClick={addLocation}>Add location</button>
          </div>
        </div>
      )}

      {tab === 'printer' && (
        <div className="card form-grid settings-panel">
          <h2>Printer</h2>
          <div className="form-grid two">
            <label>
              Name
              <input
                value={settings.printer?.name || ''}
                onChange={(e) => setSettings({ ...settings, printer: { ...settings.printer, name: e.target.value } })}
              />
            </label>
            <label>
              LAN IP
              <input
                value={settings.printer?.lan_ip || settings.env?.printer_ip || ''}
                onChange={(e) => setSettings({ ...settings, printer: { ...settings.printer, lan_ip: e.target.value } })}
              />
            </label>
            <label>
              Serial
              <input
                value={settings.printer?.serial || settings.env?.serial || ''}
                onChange={(e) => setSettings({ ...settings, printer: { ...settings.printer, serial: e.target.value } })}
              />
            </label>
            <label>
              Cloud device ID
              <input
                value={settings.printer?.cloud_device_id || ''}
                onChange={(e) => setSettings({ ...settings, printer: { ...settings.printer, cloud_device_id: e.target.value } })}
              />
            </label>
          </div>
          <div className="status-line">
            Cloud: {settings.bambu_cloud_configured ? 'Yes' : 'No'}
            {' · '}
            MQTT ({settings.bambu_mqtt_mode || 'none'}): {settings.bambu_mqtt_configured ? 'Yes' : 'No'}
          </div>
          <details className="settings-details">
            <summary>Bambu setup notes</summary>
            <p className="muted">
              Do not enable LAN Only Mode. Cloud token: MakerWorld cookie <code>token</code> →
              <code>BAMBU_CLOUD_ACCESS_TOKEN</code> in Portainer. LAN vars add AMS live state only when reachable from the deploy host.
            </p>
          </details>
          <div className="toolbar">
            <button type="button" className="secondary" onClick={skipCloudHistory}>
              Clear Bambu history &amp; restore weights
            </button>
            <button onClick={saveSettings}>Save printer</button>
          </div>
        </div>
      )}

      {tab === 'data' && (
        <div className="card form-grid settings-panel">
          <h2>CSV backup</h2>
          <button type="button" className="secondary" onClick={exportCsv}>Export spools CSV</button>
          <label className="checkbox-row">
            <input type="checkbox" checked={skipDepleted} onChange={(e) => setSkipDepleted(e.target.checked)} />
            Skip depleted spools on import (SpoolStock exports)
          </label>
          <label>
            Import CSV file
            <input type="file" accept=".csv,text/csv" onChange={importCsvFile} />
          </label>
          <label>
            Or paste CSV
            <textarea rows={6} value={csvText} onChange={(e) => setCsvText(e.target.value)} placeholder="Paste CSV export here" />
          </label>
          <button type="button" className="secondary" onClick={importCsv}>Import spools</button>
          {importResult && (
            <div className="muted">
              Format: {importResult.format || 'native'} · Created {importResult.created}, updated {importResult.updated}
              {importResult.skipped_depleted ? `, skipped ${importResult.skipped_depleted} depleted` : ''}
            </div>
          )}
        </div>
      )}

      {tab === 'advanced' && (
        <div className="card form-grid settings-panel">
          <h2>Bambu sync diagnostics</h2>
          <p className="muted">
            Timestamps from the MQTT worker. Empty <code>mqtt_last_ams_at</code> after redeploy → try AMS refresh.
          </p>
          {settings.bambu_diagnostics && (
            <dl className="diag-list">
              {Object.entries(settings.bambu_diagnostics).map(([key, value]) => (
                <div key={key} className="diag-row">
                  <dt>{key}</dt>
                  <dd>{value || '—'}</dd>
                </div>
              ))}
            </dl>
          )}
          {settings.sync_state?.length > 0 && (
            <>
              <button type="button" className="secondary" onClick={() => setShowDiagnostics((v) => !v)}>
                {showDiagnostics ? 'Hide raw sync_state' : 'Show raw sync_state'}
              </button>
              {showDiagnostics && (
                <table className="data-table">
                  <thead>
                    <tr><th>Key</th><th>Value</th><th>Updated</th></tr>
                  </thead>
                  <tbody>
                    {settings.sync_state.map((row) => (
                      <tr key={row.key}>
                        <td><code>{row.key}</code></td>
                        <td className="mono-cell">{row.value?.length > 120 ? `${row.value.slice(0, 120)}…` : (row.value || '—')}</td>
                        <td>{row.updated_at || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
