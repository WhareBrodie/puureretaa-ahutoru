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
  const [cloudTokenInput, setCloudTokenInput] = useState('');
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginCode, setLoginCode] = useState('');
  const [needsLoginCode, setNeedsLoginCode] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);
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

  const savePrinterSettings = async () => {
    try {
      setError('');
      const body = { printer: settings.printer };
      const tokenToSave = cloudTokenInput.trim();
      if (tokenToSave) {
        body.bambu_cloud_access_token = tokenToSave;
      }
      const updated = await api.settings.update(body);
      setSettings(updated);
      setCloudTokenInput('');
      if (tokenToSave) {
        const imported = updated.cloud_sync?.imported_count || 0;
        setMessage(
          updated.cloud_sync_ok === false
            ? 'Token saved, but cloud sync failed — use Sync cloud now'
            : imported
              ? `Token saved — imported ${imported} missed print(s)`
              : 'Token saved and cloud synced — no new finished prints yet',
        );
      } else {
        setMessage('Printer settings saved');
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const syncCloudNow = async () => {
    try {
      setSyncBusy(true);
      setError('');
      const result = await api.settings.syncCloud();
      if (result.settings) setSettings(result.settings);
      if (!result.ok) {
        setError(result.error || result.sync?.error || 'Cloud sync failed');
        return;
      }
      const imported = result.sync?.imported_count || 0;
      setMessage(
        imported
          ? `Cloud sync OK — imported ${imported} print(s)`
          : 'Cloud sync OK — no new prints',
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncBusy(false);
    }
  };

  const bambuLogin = async () => {
    try {
      setError('');
      const result = await api.settings.bambuLogin({
        email: loginEmail,
        password: loginPassword,
        code: loginCode || undefined,
      });
      if (result.settings) setSettings(result.settings);
      if (result.needs_code) {
        setNeedsLoginCode(true);
        setMessage(result.error || 'Enter the verification code Bambu emailed you');
        return;
      }
      if (!result.ok) {
        setError(result.error || 'Bambu login failed');
        return;
      }
      setNeedsLoginCode(false);
      setLoginPassword('');
      setLoginCode('');
      const imported = result.cloud_sync?.imported_count || 0;
      setMessage(
        imported
          ? `Signed in — imported ${imported} missed print(s)`
          : 'Signed in to Bambu cloud — token saved and cloud synced',
      );
    } catch (err) {
      setError(err.message);
    }
  };

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
          {(() => {
            const auth = settings.bambu_cloud_auth || {};
            const broken = Boolean(auth.auth_error || auth.expired);
            return (
              <div className={`status-line ${broken ? 'warning' : ''}`}>
                Cloud auth:{' '}
                {broken
                  ? 'Broken'
                  : auth.healthy
                    ? 'OK'
                    : settings.bambu_cloud_configured
                      ? 'Configured'
                      : 'Not configured'}
                {auth.token_source && auth.token_source !== 'none' ? ` (${auth.token_source})` : ''}
                {auth.days_left != null ? ` · expires in ${auth.days_left}d` : ''}
                {auth.auth_error ? ` — ${auth.auth_error}` : ''}
                {' · '}
                MQTT ({settings.bambu_mqtt_mode || 'none'}): {settings.bambu_mqtt_configured ? 'Yes' : 'No'}
                {auth.poll_ok_at ? ` · last poll ${formatDate(auth.poll_ok_at)}` : ''}
              </div>
            );
          })()}
          <label>
            Bambu cloud access token
            <input
              type="password"
              autoComplete="off"
              value={cloudTokenInput}
              onChange={(e) => setCloudTokenInput(e.target.value)}
              placeholder={settings.bambu_cloud_token_set ? 'Token saved — paste to replace' : 'Paste MakerWorld cookie token'}
            />
          </label>
          <p className="muted">
            From MakerWorld (Chrome DevTools → Application → Cookies → <code>token</code>).
            Cookie tokens are validated on save, then cloud history is synced immediately — but Bambu can revoke
            them in days/weeks with no usable refresh. Prefer <strong>Sign in with Bambu email</strong> below for a
            ~90-day token (with refresh when Bambu returns one).
          </p>
          <details className="settings-details" open>
            <summary>Sign in with Bambu email (preferred)</summary>
            <div className="form-grid two" style={{ marginTop: '0.75rem' }}>
              <label>
                Email
                <input value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} autoComplete="username" />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </label>
              {needsLoginCode && (
                <label>
                  Verification code
                  <input value={loginCode} onChange={(e) => setLoginCode(e.target.value)} autoComplete="one-time-code" />
                </label>
              )}
            </div>
            <div className="toolbar" style={{ marginTop: '0.75rem' }}>
              <button type="button" className="secondary" onClick={bambuLogin}>
                {needsLoginCode ? 'Submit code' : 'Sign in to Bambu'}
              </button>
            </div>
            <p className="muted">
              Stores a fresh access token on the server volume. If Bambu emails a code, enter it here.
              Optional Portainer <code>BAMBU_CLOUD_EMAIL</code>/<code>BAMBU_CLOUD_PASSWORD</code> can auto-relogin on 401 when 2FA is off.
            </p>
          </details>
          <details className="settings-details">
            <summary>Bambu setup notes</summary>
            <p className="muted">
              Do not enable LAN Only Mode. An optional Portainer <code>BAMBU_CLOUD_ACCESS_TOKEN</code> is used
              only when no token is saved below; saving here replaces a stale Portainer token without redeploy.
            </p>
          </details>
          <div className="toolbar">
            <button type="button" className="secondary" onClick={syncCloudNow} disabled={syncBusy}>
              {syncBusy ? 'Syncing…' : 'Sync cloud now'}
            </button>
            <button type="button" className="secondary" onClick={skipCloudHistory}>
              Clear Bambu history &amp; restore weights
            </button>
            <button onClick={savePrinterSettings}>Save printer</button>
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
