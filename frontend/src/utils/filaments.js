/** Group individual spools into filament types (brand + material + color). */

export function filamentKey({ brand, material, color_name }) {
  return encodeURIComponent([brand, material, color_name || ''].join('|'));
}

export function parseFilamentKey(key) {
  const [brand, material, color_name] = decodeURIComponent(key).split('|');
  return { brand, material, color_name: color_name || null };
}

export function isDepleted(spool) {
  return (spool.remaining_g ?? 0) <= 0;
}

export function groupSpoolsIntoFilaments(spools, { includeDepleted = false } = {}) {
  const filtered = includeDepleted ? spools : spools.filter((s) => !isDepleted(s));
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

  return [...map.values()]
    .map((g) => ({
      ...g,
      key: filamentKey(g),
      spool_count: g.spools.length,
      total_remaining_g: g.spools.reduce((sum, s) => sum + (s.remaining_g || 0), 0),
      total_capacity_g: g.spools.reduce((sum, s) => sum + (s.initial_weight_g || 1000), 0),
      low_stock_threshold_g: g.spools[0]?.low_stock_threshold_g ?? 100,
    }))
    .map((g) => ({
      ...g,
      has_low_stock: g.total_remaining_g <= g.low_stock_threshold_g,
    }))
    .sort((a, b) => {
      const nameA = (a.color_name || a.material).toLowerCase();
      const nameB = (b.color_name || b.material).toLowerCase();
      return nameA.localeCompare(nameB);
    });
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
