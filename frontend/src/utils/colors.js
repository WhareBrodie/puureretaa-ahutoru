/** Parse/store filament colour — plain hex or JSON multi-colour spec in color_hex. */

export const RAINBOW_COLORS = [
  '#EF4444',
  '#F97316',
  '#EAB308',
  '#22C55E',
  '#3B82F6',
  '#8B5CF6',
  '#EC4899',
];

export function normalizeHex(value) {
  if (!value) return null;
  const raw = String(value).trim().replace('#', '');
  if (/^[0-9A-Fa-f]{6}$/.test(raw)) return `#${raw.toUpperCase()}`;
  if (/^[0-9A-Fa-f]{8}$/.test(raw)) return `#${raw.slice(0, 6).toUpperCase()}`;
  return null;
}

/** @returns {{ mode: 'solid'|'dual'|'multicolour'|'rainbow', colors: string[] }} */
export function parseColorSpec(value) {
  if (!value) return { mode: 'solid', colors: ['#64748B'] };
  const trimmed = String(value).trim();
  if (trimmed.startsWith('{')) {
    try {
      const data = JSON.parse(trimmed);
      if (data.mode === 'rainbow') return { mode: 'rainbow', colors: RAINBOW_COLORS };
      if (data.mode === 'multi' && Array.isArray(data.colors)) {
        const colors = data.colors.map(normalizeHex).filter(Boolean);
        if (colors.length >= 3) return { mode: 'multicolour', colors };
        if (colors.length === 2) return { mode: 'dual', colors };
        if (colors.length === 1) return { mode: 'solid', colors };
      }
    } catch {
      // fall through
    }
  }
  const hex = normalizeHex(trimmed);
  return { mode: 'solid', colors: [hex || '#64748B'] };
}

export function serializeColorSpec(mode, colors) {
  if (mode === 'rainbow') return JSON.stringify({ mode: 'rainbow' });
  if (mode === 'dual' || mode === 'multicolour') {
    const normalized = colors.map(normalizeHex).filter(Boolean);
    const count = mode === 'dual' ? 2 : Math.min(9, Math.max(2, normalized.length));
    return JSON.stringify({ mode: 'multi', colors: normalized.slice(0, count) });
  }
  return normalizeHex(colors[0]) || '#22C55E';
}

export function colorSpecLabel(value) {
  const spec = parseColorSpec(value);
  if (spec.mode === 'rainbow') return 'Rainbow';
  if (spec.mode === 'dual') return spec.colors.join(' / ');
  if (spec.mode === 'multicolour') return `${spec.colors.length} colours`;
  return spec.colors[0] || '—';
}

/** CSS background for swatches, bars, etc. */
export function colorBackgroundStyle(value) {
  const spec = parseColorSpec(value);
  if (spec.mode === 'solid') {
    return { backgroundColor: spec.colors[0] };
  }
  if (spec.mode === 'dual') {
    return { background: `linear-gradient(135deg, ${spec.colors[0]}, ${spec.colors[1]})` };
  }
  if (spec.mode === 'rainbow') {
    return {
      background: `conic-gradient(from 0deg, ${RAINBOW_COLORS.join(', ')}, ${RAINBOW_COLORS[0]})`,
    };
  }
  const stops = spec.colors.join(', ');
  return { background: `conic-gradient(from 0deg, ${stops}, ${spec.colors[0]})` };
}

function polar(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

export function describeArc(cx, cy, r, startDeg, endDeg) {
  if (endDeg <= startDeg) return '';
  const start = polar(cx, cy, r, endDeg);
  const end = polar(cx, cy, r, startDeg);
  const largeArc = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
}

export function ringStrokeColors(value) {
  const spec = parseColorSpec(value);
  if (spec.mode === 'rainbow') return RAINBOW_COLORS;
  if (spec.mode === 'solid') return spec.colors;
  return spec.colors;
}
