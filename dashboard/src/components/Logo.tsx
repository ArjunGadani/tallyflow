// TallyFlow mark: tally strokes (count) on an emerald tile — ties to the name
// and the brand accent. Pure SVG, no dependency.
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span
      className="inline-grid place-items-center rounded-lg bg-emerald-600 shadow-sm"
      style={{ width: size, height: size }}
      aria-label="TallyFlow"
    >
      <svg width={size * 0.62} height={size * 0.62} viewBox="0 0 24 24" fill="none"
        stroke="white" strokeWidth="2.4" strokeLinecap="round">
        <line x1="5" y1="5" x2="5" y2="19" />
        <line x1="10" y1="5" x2="10" y2="19" />
        <line x1="15" y1="5" x2="15" y2="19" />
        <line x1="2.5" y1="15" x2="18" y2="8" />
      </svg>
    </span>
  );
}
