import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { AmountWithBase } from '../components/AmountWithBase';
import { Card } from '../components/Card';
import { ConfidenceRing } from '../components/ConfidenceRing';
import { DateRangeFilter, EMPTY_RANGE, type DateRange } from '../components/DateRangeFilter';
import { Skeleton } from '../components/Skeleton';
import { StatusBadge } from '../components/StatusBadge';
import { useAsync } from '../hooks';
import type { Invoice } from '../types';
import { fmtDate } from '../utils';

const FILTERS: Array<[string, string]> = [
  ['', 'All'], ['clean', 'Clean'], ['needs_review', 'Needs review'],
  ['credited', 'Credited'], ['superseded', 'Superseded'], ['failed', 'Failed'],
];

export function Invoices() {
  const [status, setStatus] = useState('');
  const [range, setRange] = useState<DateRange>(EMPTY_RANGE);
  const q = useAsync<Invoice[]>((s) => api.invoices(status || undefined, range, s),
                                [status, range.from, range.to]);

  return (
    <div className="space-y-5">
      <h1 className="font-display text-2xl">Invoices</h1>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex flex-wrap gap-1 p-1 bg-white border border-slate-200 rounded-xl">
          {FILTERS.map(([val, label]) => (
            <button
              key={val}
              onClick={() => setStatus(val)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                status === val ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <DateRangeFilter value={range} onChange={setRange} />
      </div>

      {q.error && <div className="bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium">{q.error}</div>}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {q.loading
          ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-32" />)
          : (q.data ?? []).map((inv, i) => (
              <Link key={inv.id} to={`/invoice/${inv.id}`}>
                <Card delay={i * 0.03} className="h-full hover:border-emerald-300 hover:shadow-pop transition cursor-pointer">
                  <div className="flex justify-between items-start gap-3">
                    <div className="min-w-0">
                      <div className="font-display text-base truncate">{inv.vendor_name || 'Unknown vendor'}</div>
                      <div className="text-xs text-slate-400 mt-0.5">{inv.invoice_number || '—'} · {fmtDate(inv.invoice_date)}</div>
                    </div>
                    <ConfidenceRing value={inv.confidence_overall} size={40} />
                  </div>
                  <div className="flex items-end justify-between mt-4">
                    <AmountWithBase total={inv.total} currency={inv.currency}
                      baseTotal={inv.base_total} baseCurrency={inv.base_currency} />
                    <StatusBadge status={inv.status} />
                  </div>
                  {inv.category && (
                    <span className="inline-block mt-3 px-2 py-0.5 rounded-md bg-slate-100 text-slate-600 text-xs font-medium">
                      {inv.category}
                    </span>
                  )}
                </Card>
              </Link>
            ))}
      </div>

      {!q.loading && (q.data ?? []).length === 0 && (
        <p className="text-slate-400 text-sm">No invoices yet. Head to Upload to add one.</p>
      )}
    </div>
  );
}
