import { useMemo } from 'react';
import SpoolRing from './SpoolRing';
import {
  parseColorSpec,
  serializeColorSpec,
  colorBackgroundStyle,
} from '../utils/colors';

const MODES = [
  { id: 'solid', label: 'Solid' },
  { id: 'dual', label: 'Dual' },
  { id: 'multicolour', label: 'Multicolour' },
  { id: 'rainbow', label: 'Rainbow' },
];

export default function ColorPickerField({ value, onChange }) {
  const spec = useMemo(() => parseColorSpec(value), [value]);

  const setMode = (mode) => {
    if (mode === 'rainbow') {
      onChange(serializeColorSpec('rainbow', []));
      return;
    }
    if (mode === 'solid') {
      onChange(serializeColorSpec('solid', [spec.colors[0] || '#22C55E']));
      return;
    }
    if (mode === 'dual') {
      const colors = spec.mode === 'dual' ? spec.colors : [spec.colors[0] || '#22C55E', '#3B82F6'];
      onChange(serializeColorSpec('dual', colors));
      return;
    }
    const colors = spec.mode === 'multicolour'
      ? spec.colors
      : [spec.colors[0] || '#22C55E', '#3B82F6', '#EAB308'];
    onChange(serializeColorSpec('multicolour', colors));
  };

  const setColorAt = (index, hex) => {
    const colors = [...spec.colors];
    while (colors.length <= index) colors.push('#22C55E');
    colors[index] = hex;
    onChange(serializeColorSpec(mode, colors));
  };

  const addColor = () => {
    if (spec.colors.length >= 9) return;
    onChange(serializeColorSpec('multicolour', [...spec.colors, '#A855F7']));
  };

  const removeColor = (index) => {
    if (spec.colors.length <= 2) return;
    const colors = spec.colors.filter((_, i) => i !== index);
    onChange(serializeColorSpec('multicolour', colors));
  };

  const mode = spec.mode;

  return (
    <div className="color-picker-field">
      <div className="color-mode-tabs">
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            className={mode === item.id ? 'active' : undefined}
            onClick={() => setMode(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="color-picker-preview">
        <SpoolRing remaining={750} capacity={1000} colorHex={value} size={52} />
        <div
          className="color-picker-swatch"
          style={colorBackgroundStyle(value)}
          aria-hidden
        />
      </div>

      {mode === 'solid' && (
        <label>
          Colour
          <input
            type="color"
            value={spec.colors[0]?.slice(0, 7) || '#22C55E'}
            onChange={(e) => onChange(serializeColorSpec('solid', [e.target.value]))}
          />
        </label>
      )}

      {mode === 'dual' && (
        <div className="color-picker-row">
          <label>
            Colour A
            <input
              type="color"
              value={spec.colors[0]?.slice(0, 7) || '#22C55E'}
              onChange={(e) => setColorAt(0, e.target.value)}
            />
          </label>
          <label>
            Colour B
            <input
              type="color"
              value={spec.colors[1]?.slice(0, 7) || '#3B82F6'}
              onChange={(e) => setColorAt(1, e.target.value)}
            />
          </label>
        </div>
      )}

      {mode === 'multicolour' && (
        <div className="color-picker-multi">
          {spec.colors.map((color, index) => (
            <div key={index} className="color-picker-multi-row">
              <label>
                {index + 1}
                <input
                  type="color"
                  value={color.slice(0, 7)}
                  onChange={(e) => setColorAt(index, e.target.value)}
                />
              </label>
              {spec.colors.length > 2 && (
                <button type="button" className="secondary" onClick={() => removeColor(index)}>Remove</button>
              )}
            </div>
          ))}
          {spec.colors.length < 9 && (
            <button type="button" className="secondary" onClick={addColor}>Add colour</button>
          )}
          <p className="muted color-picker-hint">2–9 colours, shown around the ring.</p>
        </div>
      )}

      {mode === 'rainbow' && (
        <p className="muted color-picker-hint">Full spectrum around the ring indicator.</p>
      )}
    </div>
  );
}
