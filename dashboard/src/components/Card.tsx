import { motion } from 'framer-motion';
import type { ReactNode } from 'react';

export function Card({ children, className = '', delay = 0 }: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut', delay }}
      className={`bg-white rounded-2xl border border-slate-200 shadow-sm p-5 ${className}`}
    >
      {children}
    </motion.div>
  );
}
