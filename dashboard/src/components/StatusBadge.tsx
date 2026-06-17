import type { InvoiceStatus } from '../types';
import { STATUS_LABEL, STATUS_STYLES } from '../utils';

export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const style = STATUS_STYLES[status] ?? 'bg-slate-50 text-slate-600 ring-1 ring-slate-200';
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-medium whitespace-nowrap ${style}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
