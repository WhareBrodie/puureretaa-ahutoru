import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, formatDate } from '../api';
import { formatMoney, formatUsageG } from '../utils/filaments';
import ManualPrintModal from '../components/ManualPrintModal';
import ReviewPrintModal from '../components/ReviewPrintModal';
import EditPrintModal from '../components/EditPrintModal';

export default function PrintsPage() {
  const [searchParams] = useSearchParams();
  const reviewOnly = searchParams.get('review') === '1';
  const [prints, setPrints] = useState([]);
  const [spools, setSpools] = useState([]);
  const [showManual, setShowManual] = useState(false);
  const [reviewPrint, setReviewPrint] = useState(null);
  const [editPrint, setEditPrint] = useState(null);
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([api.prints.list(reviewOnly), api.spools.list()])
      .then(([printData, spoolData]) => {
        setPrints(printData.prints || []);
        setSpools(spoolData.spools || []);
      })
      .catch((err) => setError(err.message));
  };

  useEffect(load, [reviewOnly]);

  const handleDelete = async (print) => {
    if (!window.confirm(`Delete "${print.title}"? Filament deducted for this print will be restored to linked spools.`)) {
      return;
    }
    try {
      await api.prints.remove(print.id, true);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const showReview = (print) =>
    print.needs_review ||
    (['cloud', 'mqtt', 'ftps'].includes(print.source) &&
      (print.usages || []).some((usage) => usage.used_g > 0));

  const showDeduct = (print) =>
    ['cloud', 'mqtt', 'ftps'].includes(print.source) &&
    (print.usages || []).some((usage) => usage.used_g > 0);

  const handleApplyDeductions = async (print) => {
    if (!window.confirm(`Apply filament deduction for "${print.title}" from linked spools?`)) {
      return;
    }
    try {
      const result = await api.prints.applyDeductions(print.id);
      const restored = (result.restored || [])
        .map((item) => `restored ${item.grams}g to spool ${item.spool_id}`)
        .join(', ');
      const lines = (result.deducted || [])
        .map((item) => `${item.spool_label || `Spool ${item.spool_id}`} (−${item.grams}g)`)
        .join(', ');
      const parts = [restored, lines ? `deducted: ${lines}` : '', result.message || ''].filter(Boolean);
      window.alert(parts.join('\n') || 'Deduction applied.');
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{reviewOnly ? 'Review queue' : 'Prints'}</h1>
          <p>{reviewOnly ? 'Assign spools for ambiguous filament usage' : 'Automatic Bambu imports and manual logs'}</p>
        </div>
        <button onClick={() => setShowManual(true)}>Log manual print</button>
      </div>

      {error && <div className="card danger">{error}</div>}

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Project</th>
              <th>Source</th>
              <th>Status</th>
              <th>Used</th>
              <th>Cost</th>
              <th>When</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {prints.map((print) => (
              <tr key={print.id}>
                <td>{print.title}</td>
                <td>
                  {print.project_id ? (
                    <Link to={`/prints/projects/${print.project_id}`}>{print.project_name}</Link>
                  ) : '—'}
                </td>
                <td>{print.source}</td>
                <td>
                  {print.needs_review ? <span className="badge warning">Needs review</span> : print.status}
                </td>
                <td>{formatUsageG(print.total_used_g)}</td>
                <td>{print.total_cost != null ? formatMoney(print.total_cost) : '—'}</td>
                <td>{formatDate(print.started_at || print.created_at)}</td>
                <td>
                  <div className="toolbar" style={{ justifyContent: 'flex-end' }}>
                    <button className="secondary" onClick={() => setEditPrint(print)}>Edit</button>
                    {showReview(print) && (
                      <button className="secondary" onClick={() => setReviewPrint(print)}>Review</button>
                    )}
                    {showDeduct(print) && (
                      <button className="secondary" onClick={() => handleApplyDeductions(print)}>Deduct</button>
                    )}
                    <button type="button" className="secondary danger-text" onClick={() => handleDelete(print)}>Delete</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!prints.length && <p className="muted">No prints found.</p>}
      </div>

      {showManual && (
        <ManualPrintModal
          spools={spools}
          onClose={() => setShowManual(false)}
          onSaved={() => {
            setShowManual(false);
            load();
          }}
        />
      )}

      {reviewPrint && (
        <ReviewPrintModal
          printJob={reviewPrint}
          spools={spools}
          onClose={() => setReviewPrint(null)}
          onSaved={() => {
            setReviewPrint(null);
            load();
          }}
        />
      )}

      {editPrint && (
        <EditPrintModal
          printJob={editPrint}
          onClose={() => setEditPrint(null)}
          onSaved={() => {
            setEditPrint(null);
            load();
          }}
        />
      )}
    </>
  );
}
