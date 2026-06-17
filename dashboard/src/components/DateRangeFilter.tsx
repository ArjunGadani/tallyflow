// Date-range filter (by invoice date) — quick presets + custom From/To inputs.
// Empty strings mean "open" (no bound); EMPTY_RANGE = all time.
export type DateRange = { from: string; to: string };
export const EMPTY_RANGE: DateRange = { from: '', to: '' };

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

function preset(key: string): DateRange {
  const now = new Date();
  const to = iso(now);
  const y = now.getFullYear(), m = now.getMonth();
  switch (key) {
    case 'month': return { from: iso(new Date(y, m, 1)), to };
    case '30d': { const d = new Date(now); d.setDate(d.getDate() - 29); return { from: iso(d), to }; }
    case 'quarter': return { from: iso(new Date(y, Math.floor(m / 3) * 3, 1)), to };
    case 'ytd': return { from: iso(new Date(y, 0, 1)), to };
    default: return { from: '', to: '' };
  }
}

const PRESETS = [
  { key: 'all', label: 'All time' },
  { key: 'month', label: 'This month' },
  { key: '30d', label: '30 days' },
  { key: 'quarter', label: 'This quarter' },
  { key: 'ytd', label: 'Year to date' },
];

export function DateRangeFilter({ value, onChange }: { value: DateRange; onChange: (r: DateRange) => void }) {
  const activeKey =
    PRESETS.find((p) => { const r = preset(p.key); return r.from === value.from && r.to === value.to; })?.key
    ?? (value.from || value.to ? 'custom' : 'all');

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {PRESETS.map((p) => (
        <button key={p.key} onClick={() => onChange(preset(p.key))}
          className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
            activeKey === p.key ? 'bg-emerald-600 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>
          {p.label}
        </button>
      ))}
      <span className="mx-1 h-4 w-px bg-slate-200" />
      <input type="date" value={value.from} max={value.to || undefined}
        onChange={(e) => onChange({ ...value, from: e.target.value })}
        className="px-2 py-1 rounded-lg border border-slate-200 text-xs text-slate-600 tnum" />
      <span className="text-slate-400 text-xs">to</span>
      <input type="date" value={value.to} min={value.from || undefined}
        onChange={(e) => onChange({ ...value, to: e.target.value })}
        className="px-2 py-1 rounded-lg border border-slate-200 text-xs text-slate-600 tnum" />
    </div>
  );
}
