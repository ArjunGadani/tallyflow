import { animate } from 'framer-motion';
import { useEffect, useState } from 'react';

// Animated number count-up for the summary cards.
export function CountUp({ value, prefix = '', decimals = 0 }: {
  value: number;
  prefix?: string;
  decimals?: number;
}) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const controls = animate(0, value, {
      duration: 1.1,
      ease: 'easeOut',
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value]);
  return (
    <span className="tnum">
      {prefix}
      {display.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
    </span>
  );
}
