import { useEffect, useState } from 'react';
import { api } from '../api';

export default function SettingsPage() {
  const [settings, setSettings] = useState(null);
  const [locations, setLocations] = useState([]);
  const [locationForm, setLocationForm] = useState({ name: '', description: '' });
  const [csvText, setCsvText] = useState('');
  const [skipDepleted, setSkipDepleted] = useState(true);
  const [importResult, setImportResult] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([api.settings.get(), api.locations.list()])
      .then(([settingsData, locationData]) => {
        setSettings(settingsData);
        setLocations(locationData.locations || []);
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
      const parts = [
        `Removed ${updated.deleted_imported_prints || 0} auto-imported print(s).`,
      ];
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
          <p>Printer config, alerts, locations, and CSV backup</p>
        </div>
      </div>

      {error && <div className="card danger">{error}</div>}
      {message && <div className="card">{message}</div>}

      <div className="grid grid-2">
        <div className="card form-grid">
          <h2>Printer</h2>
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
          <p className="muted">
            Do <strong>not</strong> enable LAN Only Mode. Print auto-import needs cloud credentials in Portainer.
            Easiest: log in to makerworld.com → DevTools → Application/Storage → Cookies → <code>token</code> → copy value
            into <code>BAMBU_CLOUD_ACCESS_TOKEN</code>. Or set <code>BAMBU_CLOUD_EMAIL</code> + <code>BAMBU_CLOUD_PASSWORD</code>
            if you don&apos;t use 2FA. Your LAN vars (IP, serial, access code) add live AMS + FTPS fallback only.
          </p>
          <div>
            Cloud: {settings.bambu_cloud_configured ? 'Yes' : 'No'}
            {' · '}
            MQTT ({settings.bambu_mqtt_mode || 'none'}): {settings.bambu_mqtt_configured ? 'Yes' : 'No'}
            {' · '}
            FTPS fallback: {settings.bambu_ftps_configured ? 'Yes' : 'No'}
          </div>
          <p className="muted">
            After a SpoolStock CSV import, use this once: it removes Bambu history, adds back any
            filament those imports wrongly deducted, and permanently blocks those cloud tasks from
            reappearing when the container redeploys.
          </p>
          <button type="button" className="secondary" onClick={skipCloudHistory}>
            Clear Bambu history and restore spool weights
          </button>
          <button onClick={saveSettings}>Save settings</button>
        </div>

        <div className="card form-grid">
          <h2>Alerts</h2>
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

        <div className="card form-grid">
          <h2>Storage locations</h2>
          <ul>
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
          <button className="secondary" onClick={addLocation}>Add location</button>
        </div>

        <div className="card form-grid">
          <h2>CSV backup</h2>
          <button className="secondary" onClick={exportCsv}>Export spools CSV</button>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', width: 'auto' }}>
            <input type="checkbox" checked={skipDepleted} onChange={(e) => setSkipDepleted(e.target.checked)} />
            Skip depleted spools on import (SpoolStock exports)
          </label>
          <label>
            Import SpoolStock or native CSV file
            <input type="file" accept=".csv,text/csv" onChange={importCsvFile} />
          </label>
          <label>
            Or paste CSV
            <textarea rows={8} value={csvText} onChange={(e) => setCsvText(e.target.value)} placeholder="Paste CSV export here" />
          </label>
          <button className="secondary" onClick={importCsv}>Import spools</button>
          {importResult && (
            <div className="muted">
              Format: {importResult.format || 'native'} · Created {importResult.created}, updated {importResult.updated}
              {importResult.skipped_depleted ? `, skipped ${importResult.skipped_depleted} depleted` : ''}
              {importResult.errors?.length ? `, errors: ${importResult.errors.join('; ')}` : ''}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
