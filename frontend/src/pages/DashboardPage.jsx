import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, colorStyle, formatDate } from '../api';
import { formatWeight } from '../utils/filaments';

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.dashboard()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="card danger">{error}</div>;
  if (!data) return <div className="card muted">Loading dashboard…</div>;

  const printer = data.live_printer || {};
  const state = printer.gcode_state || 'UNKNOWN';

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Inventory overview and printer status</p>
        </div>
        <Link className="button" to="/filaments">Manage filaments</Link>
      </div>

      <div className="grid grid-4">
        <div className="card">
          <div className="muted">Spools tracked</div>
          <div className="stat-value">{data.spool_count}</div>
        </div>
        <div className="card">
          <div className="muted">Filament on hand</div>
          <div className="stat-value">{formatWeight(data.total_remaining_g || 0)}</div>
        </div>
        <div className="card">
          <div className="muted">Pending reviews</div>
          <div className={`stat-value ${data.pending_reviews ? 'warning' : ''}`}>{data.pending_reviews}</div>
        </div>
        <div className="card">
          <div className="muted">Printer state</div>
          <div className="stat-value" style={{ fontSize: '1.4rem' }}>{state}</div>
          {printer.gcode_file && <div className="muted">{printer.gcode_file}</div>}
          {printer.mc_percent != null && <div className="muted">{printer.mc_percent}% complete</div>}
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: '1rem' }}>
        <div className="card">
          <h2>Low stock</h2>
          {data.low_stock_alerts?.length ? (
            <ul>
              {data.low_stock_alerts.map((alert) => (
                <li key={`${alert.type}-${alert.brand}-${alert.material}-${alert.color_name || ''}-${alert.material || ''}`}>
                  {alert.type === 'material_low'
                    ? `${alert.material}: ${Math.round(alert.total_g)}g left`
                    : `${alert.brand} ${alert.material} ${alert.color_name || ''} — ${Math.round(alert.total_remaining_g || 0)}g total`}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">All filaments above thresholds.</p>
          )}
        </div>
        <div className="card">
          <h2>Recent prints</h2>
          {data.recent_prints?.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Used</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_prints.map((print) => (
                  <tr key={print.id}>
                    <td>{print.title}</td>
                    <td>{Math.round(print.total_used_g || 0)}g</td>
                    <td>{formatDate(print.started_at || print.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No prints logged yet.</p>
          )}
        </div>
      </div>

      {data.pending_reviews > 0 && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <h2>Action needed</h2>
          <p>{data.pending_reviews} print(s) need spool assignment before filament can be deducted.</p>
          <Link className="button secondary" to="/prints?review=1">Open review queue</Link>
        </div>
      )}
    </>
  );
}
