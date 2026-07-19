import { useEffect, useState } from 'react';
import { api, colorStyle } from '../api';

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
      await api.ams.updateSlot(slot, { spool_id: spoolId ? Number(spoolId) : null });
      setMessage(
        spoolId
          ? `Slot ${slot} set — if RFID is present, that product is learned once for all future loads`
          : `Cleared slot ${slot}`,
      );
      load();
    } catch (err) {
      setError(err.message);
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
            Map a slot once per <strong>filament product</strong> (e.g. PLA Basic Black) while RFID is visible —
            the app remembers that RFID forever. Later loads of the same product auto-pick the open spool
            (partially used; if all are new, any match). Non-RFID filament still needs manual slot picks.
          </p>
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
                  <div className="muted">{slot.brand} · {Math.round(slot.remaining_g || 0)}g</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
