import { useMemo, useState } from 'react';
import { api } from '../api';
import { compareSpoolsForSelect, formatSpoolSelectLabel, formatUsageG } from '../utils/filaments';

function buildInitialAssignments(usages) {
  return usages.map((usage) => ({
    usage_id: usage.id,
    spool_id: usage.spool_id || '',
    used_g: usage.used_g ?? 0,
    split_group: usage.split_group || null,
    split_role: usage.split_role || null,
    ams_slot: usage.ams_slot,
    material: usage.material,
    color: usage.color,
    swap_old_remaining_g: usage.swap_old_remaining_g,
  }));
}

function groupAssignments(assignments) {
  const groups = [];
  const seen = new Set();
  for (const item of assignments) {
    if (item.split_group) {
      if (seen.has(item.split_group)) continue;
      seen.add(item.split_group);
      const members = assignments.filter((row) => row.split_group === item.split_group);
      groups.push({ type: 'split', key: item.split_group, members });
    } else {
      groups.push({ type: 'single', key: String(item.usage_id), members: [item] });
    }
  }
  return groups;
}

export default function ReviewPrintModal({ printJob, spools, onClose, onSaved }) {
  const weightedUsages = useMemo(
    () => (printJob.usages || []).filter((usage) => usage.used_g > 0 || usage.split_group),
    [printJob.usages],
  );
  const [assignments, setAssignments] = useState(() => buildInitialAssignments(weightedUsages));
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  const groups = groupAssignments(assignments);
  const hasSplit = assignments.some((item) => item.split_group);

  const updateAssignment = (usageId, patch) => {
    setAssignments((prev) =>
      prev.map((item) => (item.usage_id === usageId ? { ...item, ...patch } : item)),
    );
  };

  const splitSumOk = (members) => {
    const original = weightedUsages
      .filter((usage) => usage.split_group === members[0].split_group)
      .reduce((sum, usage) => sum + (Number(usage.used_g) || 0), 0);
    const current = members.reduce((sum, item) => sum + (Number(item.used_g) || 0), 0);
    return Math.abs(current - original) < 0.06;
  };

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    for (const group of groups) {
      if (group.type === 'split' && !splitSumOk(group.members)) {
        const original = weightedUsages
          .filter((usage) => usage.split_group === group.key)
          .reduce((sum, usage) => sum + (Number(usage.used_g) || 0), 0);
        setError(`Slot split grams must still sum to ${formatUsageG(original)}.`);
        return;
      }
    }
    try {
      await api.prints.review(printJob.id, {
        assignments: assignments.map((item) => ({
          usage_id: item.usage_id,
          spool_id: item.spool_id ? Number(item.spool_id) : null,
          used_g: Number(item.used_g) || 0,
        })),
        review_note: note,
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="card modal form-grid" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>Review print</h2>
        <p className="muted">
          {printJob.title} — confirm which spool was used
          {hasSplit
            ? '. Mid-print spool swap detected — edit the suggested split before deducting.'
            : weightedUsages.length === 1
              ? ''
              : ` (${weightedUsages.length} materials)`}
          .
        </p>
        {error && <div className="danger">{error}</div>}

        {groups.map((group) => {
          if (group.type === 'split') {
            const slot = group.members[0]?.ams_slot || '?';
            const material = group.members[0]?.material;
            const hint = group.members[0]?.swap_old_remaining_g;
            const original = weightedUsages
              .filter((usage) => usage.split_group === group.key)
              .reduce((sum, usage) => sum + (Number(usage.used_g) || 0), 0);
            const current = group.members.reduce((sum, item) => sum + (Number(item.used_g) || 0), 0);
            return (
              <div key={group.key} className="card" style={{ background: 'var(--panel-2)' }}>
                <strong>Slot {slot} — mid-print swap</strong>
                <div className="muted">
                  {material || 'Filament'} · total {formatUsageG(original)}
                  {hint != null ? ` · inventory thought old spool had ${formatUsageG(hint)} left` : ''}
                </div>
                {!splitSumOk(group.members) && (
                  <div className="danger" style={{ marginTop: '0.5rem' }}>
                    Parts sum to {formatUsageG(current)}; must equal {formatUsageG(original)}.
                  </div>
                )}
                {group.members
                  .slice()
                  .sort((a, b) => (a.split_role === 'old' ? -1 : 1))
                  .map((item) => (
                    <div key={item.usage_id} style={{ marginTop: '0.75rem' }}>
                      <strong>{item.split_role === 'old' ? 'Emptying spool' : 'Replacement spool'}</strong>
                      <label>
                        Grams
                        <input
                          type="number"
                          min="0"
                          step="0.1"
                          value={item.used_g}
                          onChange={(e) => updateAssignment(item.usage_id, { used_g: e.target.value })}
                          required
                        />
                      </label>
                      <label>
                        Assign spool
                        <select
                          value={item.spool_id || ''}
                          onChange={(e) => updateAssignment(item.usage_id, { spool_id: e.target.value })}
                          required={Number(item.used_g) > 0}
                        >
                          <option value="">Choose spool</option>
                          {spools
                            .filter((spool) => !item.material || spool.material === item.material)
                            .sort(compareSpoolsForSelect)
                            .map((spool) => (
                              <option key={spool.id} value={spool.id}>
                                {formatSpoolSelectLabel(spool)}
                              </option>
                            ))}
                        </select>
                      </label>
                    </div>
                  ))}
              </div>
            );
          }

          const item = group.members[0];
          const usage = weightedUsages.find((row) => row.id === item.usage_id) || item;
          return (
            <div key={group.key} className="card" style={{ background: 'var(--panel-2)' }}>
              <strong>Slot {usage.ams_slot || '?'}</strong>
              <div className="muted">
                {usage.material} {usage.color || ''} — {formatUsageG(usage.used_g)}
              </div>
              <label>
                Assign spool
                <select
                  value={item.spool_id || ''}
                  onChange={(e) => updateAssignment(item.usage_id, { spool_id: e.target.value })}
                >
                  <option value="">Choose spool</option>
                  {spools
                    .filter((spool) => !usage.material || spool.material === usage.material)
                    .sort(compareSpoolsForSelect)
                    .map((spool) => (
                      <option key={spool.id} value={spool.id}>
                        {formatSpoolSelectLabel(spool)}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          );
        })}

        <label>
          Review note
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <div className="toolbar">
          <button type="submit">Apply deductions</button>
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
