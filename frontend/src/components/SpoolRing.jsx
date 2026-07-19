export default function SpoolRing({ remaining = 0, capacity = 1000, colorHex, size = 44 }) {
  const pct = capacity > 0 ? Math.min(1, Math.max(0, remaining / capacity)) : 0;
  const stroke = 4;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const filled = circumference * pct;
  const raw = (colorHex || '64748b').replace('#', '');
  const color = `#${raw.slice(0, 6)}`;

  return (
    <svg className="spool-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke="rgba(148, 163, 184, 0.22)"
        strokeWidth={stroke}
      />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeDasharray={`${filled} ${circumference}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
      />
    </svg>
  );
}
