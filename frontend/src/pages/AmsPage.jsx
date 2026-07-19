import { useEffect, useState } from 'react';
import { api, colorStyle, formatDate } from '../api';

function mqttColor(hex) {
  if (!hex) return null;
  const value = hex.replace(/[^0-9A-Fa-f]/g, '').slice(0, 6);
  return value ? `#${value}` : null;
}

export default function AmsPage() {
  const [live, setLive] = useState(null);
  const [spools, setSpools] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = () => {
    Promise.all([api.ams.live(), api.spools.list()])
      .then(([liveData, spoolData]) => {
        setLive(liveData);
        setSpools(spoolData.spools || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const updateSlot = async (slot, spoolId) => {
    try {
      const tray = mqtt[String(slot)] || {};
      await api.ams.updateSlot(slot, {
        spool_id: spoolId ? Number(spoolId) : null,
        tray,
      });
      setMessage(
        spoolId
          ? `Slot ${slot} mapped — RFID product learned for this tray only`
          : `Cleared slot ${slot}`,
      );
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const clearRfidLearns = async () => {
    if (!window.confirm('Clear all learned RFID products? You will need to re-pick each AMS slot once.')) {
      return;
    }
    try {
      const result = await api.ams.clearRfidLearns();
      setMessage(`Cleared ${result.deleted || 0} learned RFID product(s). Re-map each slot from the dropdown.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const refreshFromPrinter = async () => {
    setRefreshing(true);
    setError('');
    try {
      const result = await api.ams.refresh();
      setLive(result);
      if (result.probe?.ok) {
        setMessage(`AMS refreshed via ${result.probe.mode || 'mqtt'} — trays: ${Object.keys(result.ams || {}).join(', ') || 'none'}`);
      } else {
        const parts = [result.probe?.error || 'Refresh did not return AMS tray data'];
        if (result.probe?.hint) parts.push(result.probe.hint);
        if (result.probe?.note) parts.push(result.probe.note);
        setError(parts.join(' '));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  };

  const slots = live?.slots || [];
  const mqtt = live?.ams || {};

  return (
    <>
      <div className="page-header">
        <div>
          <h1>AMS setup</h1>
          <p>
            Pick the correct spool per slot once — your choice is kept; MQTT will not change it.
            RFID is learned only when you use the dropdown (one product per tray colour).
          </p>
        </div>
        <div className="toolbar">
          <button type="button" className="secondary" disabled={refreshing} onClick={refreshFromPrinter}>
            {refreshing ? 'Refreshing…' : 'Refresh from printer'}
          </button>
          <button type="button" className="secondary" onClick={clearRfidLearns}>
            Clear learned RFID
          </button>
        </div>
      </div>

      {error && <div className="card danger">{error}</div>}
      {message && <div className="card">{message}</div>}

      <div className="ams-board">
        {slots.map((slot) => {
          const tray = mqtt[String(slot.slot)] || {};
          const trayColor = mqttColor(tray.tray_color) || slot.color_hex;
          return (
            <div key={slot.slot} className="card ams-slot">
              <div className="ams-slot-header">
                <strong>Slot {slot.slot}</strong>
                {trayColor && <span className="color-dot" style={colorStyle(trayColor)} />}
              </div>
              <div className="muted">
                MQTT: {tray.tray_type || '—'} {tray.tray_color ? `#${String(tray.tray_color).slice(0, 6)}` : ''}
              </div>
              {tray.tag_uid ? (
                <div className="badge">RFID product …{tray.tag_uid.slice(-6)}</div>
              ) : (
                <div className="muted">No RFID — manual mapping only</div>
              )}
              <label>
                Teach / override spool
                <select
                  value={slot.spool_id || slot.mapped_spool_id || ''}
                  onChange={(e) => updateSlot(slot.slot, e.target.value)}
                >
                  <option value="">Unassigned</option>
                  {spools.map((spool) => (
                    <option key={spool.id} value={spool.id}>
                      {spool.brand} {spool.material} {spool.color_name || ''}
                    </option>
                  ))}
                </select>
              </label>
              {slot.brand && (
                <div>
                  <strong>{slot.color_name || slot.material}</strong>
                  <div className="muted">
                    {slot.brand} · {Math.round(slot.remaining_g || 0)}g
                    {slot.last_weighed_at ? ` · weighed ${formatDate(slot.last_weighed_at)}` : ' · never weighed'}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
