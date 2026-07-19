const API = '/api';

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = data.error || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

export const api = {
  health: () => request('/health'),
  dashboard: () => request('/dashboard'),
  stats: () => request('/stats'),
  alerts: () => request('/alerts'),
  settings: {
    get: () => request('/settings'),
    update: (body) => request('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  },
  locations: {
    list: () => request('/locations'),
    create: (body) => request('/locations', { method: 'POST', body: JSON.stringify(body) }),
    update: (id, body) => request(`/locations/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    remove: (id) => request(`/locations/${id}`, { method: 'DELETE' }),
  },
  spools: {
    list: (params = {}) => {
      const query = new URLSearchParams(params).toString();
      return request(`/spools${query ? `?${query}` : ''}`);
    },
    get: (id) => request(`/spools/${id}`),
    create: (body) => request('/spools', { method: 'POST', body: JSON.stringify(body) }),
    update: (id, body) => request(`/spools/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
    remove: (id) => request(`/spools/${id}`, { method: 'DELETE' }),
    calculateWeight: (id, totalWeightG) =>
      request(`/spools/${id}/calculate-weight`, {
        method: 'POST',
        body: JSON.stringify({ total_weight_g: totalWeightG }),
      }),
    addDryingLog: (id, body) =>
      request(`/spools/${id}/drying-log`, { method: 'POST', body: JSON.stringify(body) }),
    uploadPhoto: async (id, file) => {
      const form = new FormData();
      form.append('photo', file);
      const response = await fetch(`${API}/spools/${id}/photo`, { method: 'POST', body: form });
      if (!response.ok) throw new Error('Photo upload failed');
      return response.json();
    },
    linkBambuTag: (id, tagUid, trayInfoIdx) =>
      request(`/spools/${id}/link-bambu-tag`, {
        method: 'POST',
        body: JSON.stringify({ tag_uid: tagUid, tray_info_idx: trayInfoIdx }),
      }),
  },
  emptySpoolWeights: (brand, model) => {
    const params = new URLSearchParams();
    if (brand) params.set('brand', brand);
    if (model) params.set('model', model);
    const query = params.toString();
    return request(`/empty-spool-weights${query ? `?${query}` : ''}`);
  },
  prints: {
    list: (pendingReview = false) =>
      request(`/prints${pendingReview ? '?pending_review=true' : ''}`),
    get: (id) => request(`/prints/${id}`),
    create: (body) => request('/prints', { method: 'POST', body: JSON.stringify(body) }),
    review: (id, body) => request(`/prints/${id}/review`, { method: 'POST', body: JSON.stringify(body) }),
  },
  ams: {
    slots: () => request('/ams/slots'),
    live: () => request('/ams/live'),
    updateSlot: (slot, body) => request(`/ams/slots/${slot}`, { method: 'PUT', body: JSON.stringify(body) }),
  },
  exportCsv: () => request('/export/csv'),
  importCsv: (csv, updateExisting = false) =>
    request('/import/csv', {
      method: 'POST',
      body: JSON.stringify({ csv, update_existing: updateExisting }),
    }),
};

export function photoUrl(spool) {
  if (!spool?.photo_path) return null;
  const filename = spool.photo_path.split('/').pop();
  return `/api/photos/${filename}`;
}

export function colorStyle(hex) {
  if (!hex) return { background: 'linear-gradient(135deg, #64748b, #334155)' };
  return { backgroundColor: hex.startsWith('#') ? hex : `#${hex.slice(0, 6)}` };
}

export function formatDate(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export function daysSince(value) {
  if (!value) return null;
  const diff = Date.now() - new Date(value).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}
