import { useEffect, useState } from 'react';
import { api } from '../api';

function BarChart({ rows, labelKey, valueKey }) {
  const max = Math.max(...rows.map((row) => row[valueKey] || 0), 1);
  return (
    <div className="bar-chart">
      {rows.map((row) => (
        <div className="bar-row" key={row[labelKey]}>
          <div>{row[labelKey]}</div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${((row[valueKey] || 0) / max) * 100}%` }} />
          </div>
          <div>{Math.round(row[valueKey] || 0)}g</div>
        </div>
      ))}
    </div>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([api.stats(), api.alerts()])
      .then(([statsData, alertsData]) => {
        setStats(statsData);
        setAlerts(alertsData);
      })
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="card danger">{error}</div>;
  if (!stats) return <div className="card muted">Loading stats…</div>;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Stats</h1>
          <p>Usage summaries and low-stock alerts</p>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h2>Material usage</h2>
          <BarChart rows={stats.material_usage || []} labelKey="material" valueKey="total_g" />
        </div>
        <div className="card">
          <h2>Top colors</h2>
          <BarChart
            rows={(stats.top_colors || []).map((row) => ({
              ...row,
              label: row.color_name || row.color_hex || 'Unknown',
            }))}
            labelKey="label"
            valueKey="total_g"
          />
        </div>
        <div className="card">
          <h2>Monthly consumption</h2>
          <BarChart rows={stats.monthly_usage || []} labelKey="month" valueKey="total_g" />
        </div>
        <div className="card">
          <h2>Low stock</h2>
          {alerts?.reorder?.length ? (
            <ul>
              {alerts.reorder.map((item) => (
                <li key={item.spool_id}>
                  {item.brand} {item.material} {item.color_name} — {Math.round(item.remaining_g || 0)}g left
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No spools are low yet.</p>
          )}
        </div>
      </div>
    </>
  );
}
