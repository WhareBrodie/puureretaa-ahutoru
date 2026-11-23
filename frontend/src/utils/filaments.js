/** Group individual spools into filament types (brand + material + color). */

export function filamentKey({ brand, material, color_name }) {
  return encodeURIComponent([brand, material, color_name || ''].join('|'));
}

export function parseFilamentKey(key) {
  const [brand, material, color_name] = decodeURIComponent(key).split('|');
  return { brand, material, color_name: color_name || null };
}

/** Manual archive flag — zero remaining does not auto-archive. */
export function isArchived(spool) {
  return Boolean(spool.archived);
}

/** Spools available for AMS / review / manual-print selects (keep current selection). */
export function spoolsForSelect(spools, selectedSpoolId = null) {
  return spools.filter(
    (spool) =>
      !isArchived(spool)
      || String(spool.id) === String(selectedSpoolId || ''),
  );
}

/** Normalize Bambu / inventory material tokens for comparison. */
export function normalizeMaterial(value) {
  return String(value || '')
    .toUpperCase()
    .replace(/_/g, '-')
    .replace(/\s+/g, '-')
    .trim();
}

export function isSupportMaterial(value) {
  const token = normalizeMaterial(value);
  if (!token) return false;
  return (
    token === 'PLA-S'
    || token === 'PETG-S'
    || token === 'SUPPORT'
    || token === 'SUPPORT-FOR-PLA'
    || token === 'SUPPORT-FOR-PA'
    || token === 'SUPPORT-FOR-PETG'
    || token === 'SUPPORT-PA'
    || token === 'SUPPORT-PETG'
    || token.startsWith('SUPPORT')
  );
}

function isPlaFamily(value) {
  const token = normalizeMaterial(value);
  return token.startsWith('PLA') && !isSupportMaterial(token);
}

/**
 * Match print-usage materials to inventory spools for review dropdowns.
 * Mirrors server/bambu/print_processor._materials_compatible, plus bidirectional
 * PLA family matching so PLA Matte / PLA Basic both appear when Bambu reports "PLA".
 */
export function materialsCompatible(usageMaterial, spoolMaterial) {
  const usage = normalizeMaterial(usageMaterial);
  const spool = normalizeMaterial(spoolMaterial);
  if (!usage || usage === 'UNKNOWN') return true;
  if (usage === spool) return true;
  if (isSupportMaterial(usage) && isSupportMaterial(spool)) return true;
  if (isPlaFamily(usage) && isPlaFamily(spool)) return true;
  // Generic "PLA" from cloud also covers PLA-MATTE / PLA-SILK etc. (already covered
  // by isPlaFamily, but keep PETG/ABS-style prefix expansion for non-PLA later).
  if (usage === 'PLA' && spool.startsWith('PLA') && !isSupportMaterial(spool)) return true;
  return false;
}

/** Alphabetical by brand → material → colour; heavier spools first within the same filament. */
export function compareSpoolsForSelect(a, b) {
  for (const field of ['brand', 'material', 'color_name']) {
    const cmp = (a[field] || '').localeCompare(b[field] || '', undefined, { sensitivity: 'base' });
    if (cmp !== 0) return cmp;
  }
  const remA = a.remaining_g ?? 0;
  const remB = b.remaining_g ?? 0;
  if (remB !== remA) return remB - remA;
  return (a.id ?? 0) - (b.id ?? 0);
}

export function formatSpoolSelectLabel(spool) {
  const name = [spool.brand, spool.material, spool.color_name].filter(Boolean).join(' ');
  return `${name} (${Math.round(spool.remaining_g ?? 0)}g)`;
}

export function groupSpoolsIntoFilaments(spools, { includeArchived = false } = {}) {
  const stockByKey = new Map();
  for (const spool of spools) {
    if (isArchived(spool)) continue;
    const key = `${spool.brand}|${spool.material}|${spool.color_name || ''}`;
    if (!stockByKey.has(key)) {
      stockByKey.set(key, {
        total_remaining_g: 0,
        low_stock_threshold_g: spool.low_stock_threshold_g ?? 100,
        active_spool_count: 0,
      });
    }
    const stock = stockByKey.get(key);
    stock.total_remaining_g += spool.remaining_g || 0;
    stock.active_spool_count += 1;
  }

  const filtered = includeArchived ? spools : spools.filter((s) => !isArchived(s));
  const map = new Map();

  for (const spool of filtered) {
    const key = `${spool.brand}|${spool.material}|${spool.color_name || ''}`;
    if (!map.has(key)) {
      map.set(key, {
        brand: spool.brand,
        material: spool.material,
        color_name: spool.color_name,
        color_hex: spool.color_hex,
        photo_path: spool.photo_path,
        spools: [],
        updated_at: spool.updated_at,
      });
    }
    const group = map.get(key);
    group.spools.push(spool);
    if (spool.updated_at > group.updated_at) group.updated_at = spool.updated_at;
    if (spool.photo_path) group.photo_path = spool.photo_path;
    if (spool.color_hex && !group.color_hex) group.color_hex = spool.color_hex;
  }

  // Include archived-only filaments when the toggle is on so retired types still appear.
  if (includeArchived) {
    for (const spool of spools) {
      const key = `${spool.brand}|${spool.material}|${spool.color_name || ''}`;
      if (map.has(key)) continue;
      map.set(key, {
        brand: spool.brand,
        material: spool.material,
        color_name: spool.color_name,
        color_hex: spool.color_hex,
        photo_path: spool.photo_path,
        spools: spools.filter(
          (item) =>
            item.brand === spool.brand
            && item.material === spool.material
            && (item.color_name || '') === (spool.color_name || ''),
        ),
        updated_at: spool.updated_at,
      });
    }
  }

  return [...map.values()]
    .map((g) => {
      const stock = stockByKey.get(`${g.brand}|${g.material}|${g.color_name || ''}`);
      const activeCount = stock?.active_spool_count ?? 0;
      return {
        ...g,
        key: filamentKey(g),
        spool_count: g.spools.length,
        total_remaining_g: stock?.total_remaining_g ?? 0,
        total_capacity_g: g.spools
          .filter((s) => !isArchived(s))
          .reduce((sum, s) => sum + (s.initial_weight_g || 1000), 0),
        low_stock_threshold_g: stock?.low_stock_threshold_g ?? 100,
        no_stock: activeCount === 0 && g.spools.length > 0,
        archived_only: activeCount === 0 && g.spools.every(isArchived),
      };
    })
    .map((g) => ({
      ...g,
      has_low_stock: g.no_stock || g.total_remaining_g <= g.low_stock_threshold_g,
    }))
    .sort((a, b) => {
      const nameA = (a.color_name || a.material).toLowerCase();
      const nameB = (b.color_name || b.material).toLowerCase();
      return nameA.localeCompare(nameB);
    });
}

export function formatUsageG(g) {
  if (g == null || Number.isNaN(g)) return '—';
  return `${Number(g).toFixed(1)}g`;
}

export function formatWeight(g) {
  if (g == null || Number.isNaN(g)) return '—';
  if (g >= 1000) return `${(g / 1000).toFixed(2)} kg`;
  return `${Math.round(g)} g`;
}

/** Cost of used_g based on spool purchase price and initial weight. */
export function usageCost(usedG, purchasePrice, initialWeightG) {
  if (purchasePrice == null || !initialWeightG || initialWeightG <= 0 || !usedG) return null;
  return (usedG * purchasePrice) / initialWeightG;
}

export function formatMoney(amount) {
  if (amount == null || Number.isNaN(amount)) return '—';
  return `$${amount.toFixed(2)}`;
}

export function groupSpoolsByLocation(spools, locations) {
  const byId = new Map(locations.map((l) => [l.id, l]));
  const groups = new Map();

  for (const loc of locations) {
    groups.set(loc.id, { location: loc, spools: [] });
  }
  groups.set(null, { location: { id: null, name: 'Unassigned' }, spools: [] });

  for (const spool of spools) {
    const locId = spool.location_id ?? null;
    if (!groups.has(locId)) {
      const loc = byId.get(locId) || { id: locId, name: spool.location_name || 'Unknown' };
      groups.set(locId, { location: loc, spools: [] });
    }
    groups.get(locId).spools.push(spool);
  }

  return [...groups.values()]
    .filter((g) => g.spools.length > 0)
    .sort((a, b) => {
      if (a.location.id == null) return 1;
      if (b.location.id == null) return -1;
      return a.location.name.localeCompare(b.location.name, undefined, { sensitivity: 'base' });
    });
}
