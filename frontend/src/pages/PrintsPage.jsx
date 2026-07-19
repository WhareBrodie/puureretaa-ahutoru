import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, formatDate } from '../api';
import { formatMoney } from '../utils/filaments';
import ManualPrintModal from '../components/ManualPrintModal';
import ReviewPrintModal from '../components/ReviewPrintModal';

export default function PrintsPage() {
  const [searchParams] = useSearchParams();
  const reviewOnly = searchParams.get('review') === '1';
  const [prints, setPrints] = useState([]);
  const [spools, setSpools] = useState([]);
  const [showManual, setShowManual] = useState(false);
  const [reviewPrint, setReviewPrint] = useState(null);
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
                <td>{print.source}</td>
                <td>
                  {print.needs_review ? <span className="badge warning">Needs review</span> : print.status}
                </td>
                <td>{Math.round(print.total_used_g || 0)}g</td>
                <td>{print.total_cost != null ? formatMoney(print.total_cost) : '—'}</td>
                <td>{formatDate(print.started_at || print.created_at)}</td>
                <td>
                  {print.needs_review && (
                    <button className="secondary" onClick={() => setReviewPrint(print)}>Review</button>
                  )}
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
    </>
  );
}
