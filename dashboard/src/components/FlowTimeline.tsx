import { motion } from 'framer-motion';
import { Check, X } from 'lucide-react';
import type { FlowEvent } from '../types';
import { fmtDateTime, isFailedStep, stepDetail, stepLabel } from '../utils';

// Live processing-flow timeline (§9): ordered, animated, with a connector rail.
export function FlowTimeline({ events, animated = true }: { events: FlowEvent[]; animated?: boolean }) {
  if (!events.length) return <p className="text-slate-400 text-sm">No processing events yet.</p>;
  return (
    <ol className="relative">
      <span className="absolute left-[11px] top-1 bottom-1 w-px bg-slate-200" aria-hidden />
      {events.map((ev, i) => {
        const failed = isFailedStep(ev.type);
        const detail = stepDetail(ev);
        return (
          <motion.li
            key={`${ev.type}-${i}`}
            initial={animated ? { opacity: 0, x: -8 } : false}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: animated ? i * 0.08 : 0, duration: 0.25, ease: 'easeOut' }}
            className="relative flex items-start gap-3 pb-4 last:pb-0"
          >
            <span className={`relative z-10 mt-0.5 h-6 w-6 shrink-0 rounded-full grid place-items-center ring-4 ring-white ${
              failed ? 'bg-rose-100 text-rose-600' : 'bg-emerald-100 text-emerald-700'
            }`}>
              {failed ? <X size={13} strokeWidth={2.5} /> : <Check size={13} strokeWidth={2.5} />}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-slate-800">{stepLabel(ev.type)}</div>
              {detail && <div className="text-xs text-slate-500 mt-0.5">{detail}</div>}
            </div>
            <time className="text-xs text-slate-400 tnum shrink-0">{fmtDateTime(ev.ts)}</time>
          </motion.li>
        );
      })}
    </ol>
  );
}
