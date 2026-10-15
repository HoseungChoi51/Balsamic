import { useEffect, useId, useState } from 'react';

const units = { s: 1, min: 60, h: 3600 } as const;
type Unit = keyof typeof units;
const names: Record<Unit, string> = { s: 'seconds', min: 'minutes', h: 'hours' };

function shown(value: string, unit: Unit): string {
  const number = Number(value);
  return value === '' || !Number.isFinite(number) ? value : String(Number((number / units[unit]).toPrecision(6)));
}

/**
 * A length of time entered in seconds, minutes or hours and kept in seconds, as the commands take it.
 * Long allocations default to minutes; the unit can be changed beside the number.
 */
export function DurationField({ label, seconds, onChange, unit: initial = 'min', hint, min = 1, max, required = true }: {
  label: string; seconds: string; onChange: (seconds: string) => void; unit?: Unit; hint?: string; min?: number; max?: number; required?: boolean;
}) {
  const id = useId();
  const [unit, setUnit] = useState<Unit>(initial);
  const [text, setText] = useState(shown(seconds, initial));
  // A value set from outside (another field, a reset) is shown in the current unit.
  useEffect(() => { if (Number(text) * units[unit] !== Number(seconds)) setText(shown(seconds, unit)); }, [seconds]);
  function change(value: string) {
    setText(value);
    const number = Number(value);
    onChange(value === '' || !Number.isFinite(number) ? value : String(Math.round(number * units[unit] * 1000) / 1000));
  }
  return <div className="field duration-field"><label htmlFor={id}>{label} ({names[unit]})</label>
    <div className="duration-input">
      <input id={id} type="number" min={min / units[unit]} max={max ? max / units[unit] : undefined} step="any" value={text} required={required}
        onChange={event => change(event.target.value)} aria-describedby={hint ? `${id}-hint` : undefined} />
      <select aria-label={`Unit of ${label.toLowerCase()}`} value={unit} onChange={event => { const next = event.target.value as Unit; setUnit(next); setText(shown(seconds, next)); }}>
        {(Object.keys(units) as Unit[]).map(key => <option key={key} value={key}>{key}</option>)}
      </select>
    </div>{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
