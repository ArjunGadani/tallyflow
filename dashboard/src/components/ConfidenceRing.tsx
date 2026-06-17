// Display-only confidence ring (0..1). Green >=75%, amber >=50%, rose below.
export function ConfidenceRing({ value, size = 44 }: { value: number | string; size?: number }) {
  // confidence_overall arrives as a string over the wire (precision-preserving
  // JSON); coerce defensively so the ring maths is numeric.
  const pct = Math.max(0, Math.min(1, Number(value) || 0));
  const stroke = 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const color = pct >= 0.75 ? '#059669' : pct >= 0.5 ? '#d97706' : '#e11d48';
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} title={`Confidence ${Math.round(pct * 100)}%`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#eef0f5" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none"
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-[10px] font-extrabold tnum" style={{ color }}>
        {Math.round(pct * 100)}
      </span>
    </div>
  );
}
