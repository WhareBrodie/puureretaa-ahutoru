import { useId } from 'react';
import { describeArc, parseColorSpec, ringStrokeColors } from '../utils/colors';

export default function SpoolRing({ remaining = 0, capacity = 1000, colorHex, size = 44 }) {
  const spec = parseColorSpec(colorHex);
  const pct = capacity > 0 ? Math.min(1, Math.max(0, remaining / capacity)) : 0;
  const stroke = 4;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const filled = circumference * pct;
  const gradId = useId().replace(/:/g, '');

  if (spec.mode === 'solid') {
    const color = spec.colors[0];
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

  const filledDeg = pct * 360;
  const colors = ringStrokeColors(colorHex);

  if (spec.mode === 'dual' && filledDeg > 0) {
    return (
      <svg className="spool-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={colors[0]} />
            <stop offset="100%" stopColor={colors[1]} />
          </linearGradient>
        </defs>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(148, 163, 184, 0.22)" strokeWidth={stroke} />
        <path
          d={describeArc(cx, cy, r, -90, -90 + filledDeg)}
          fill="none"
          stroke={`url(#${gradId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
        />
      </svg>
    );
  }

  if (filledDeg <= 0) {
    return (
      <svg className="spool-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(148, 163, 184, 0.22)" strokeWidth={stroke} />
      </svg>
    );
  }

  const segmentDeg = filledDeg / colors.length;
  return (
    <svg className="spool-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(148, 163, 184, 0.22)" strokeWidth={stroke} />
      {colors.map((color, index) => {
        const start = -90 + index * segmentDeg;
        const end = start + segmentDeg;
        return (
          <path
            key={`${color}-${index}`}
            d={describeArc(cx, cy, r, start, end)}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap={index === colors.length - 1 ? 'round' : 'butt'}
          />
        );
      })}
    </svg>
  );
}
