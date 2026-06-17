import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { Card } from '../components/Card';
import { MoneyText } from '../components/MoneyText';
import { Skeleton } from '../components/Skeleton';
import { useAsync } from '../hooks';
import type { ReviewAction, ReviewQueue as RQ } from '../types';
import { fmtDate } from '../utils';

export function ReviewQueue() {
  const q = useAsync<RQ>((s) => api.reviewQueue(s), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const act = async (id: string, action: ReviewAction) => {
    setBusy(id); setErr(null);
    try {
      await api.review(id, action);
      q.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const dlAct = async (id: string, kind: 'retry' | 'dismiss') => {
    setBusy(id); setErr(null);
    try {
      if (kind === 'retry') await api.retryDeadLetter(id);
      else await api.dismissDeadLetter(id);
      q.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-display text-2xl">Review queue</h1>
        <p className="text-sm text-slate-500 mt-1">
          Flagged for a human decision. Approve (counts toward spend) or dismiss (excluded) —
          extracted numbers can't be edited; this is a trust gate, not an editor.
        </p>
      </div>

      {err && <div className="bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium">{err}</div>}

      {q.loading ? (
        <Skeleton className="h-32" />
      ) : (
        <>
          <div className="space-y-2">
            {(q.data?.needs_review ?? []).map((inv) => (
              <Card key={inv.id} className="flex flex-wrap items-center gap-4 justify-between">
                <Link to={`/invoice/${inv.id}`} className="min-w-0">
                  <div className="font-display text-base">{inv.vendor_name || 'Unknown'}</div>
                  <div className="text-sm text-slate-400 mt-0.5">
                    {inv.invoice_number || '—'} · {fmtDate(inv.invoice_date)} ·{' '}
                    <MoneyText value={inv.total} currency={inv.currency} />
                  </div>
                </Link>
                <div className="flex gap-2">
                  <button disabled={busy === inv.id} onClick={() => act(inv.id, 'approve')}
                    className="px-3.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium disabled:opacity-50 transition-colors">
                    Approve
                  </button>
                  <button disabled={busy === inv.id} onClick={() => act(inv.id, 'dismiss')}
                    className="px-3.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 text-sm font-medium disabled:opacity-50 transition-colors">
                    Dismiss
                  </button>
                </div>
              </Card>
            ))}
            {(q.data?.needs_review ?? []).length === 0 && (
              <p className="text-slate-400 text-sm">Nothing needs review.</p>
            )}
          </div>

          {(q.data?.dead_letter ?? []).length > 0 && (
            <div className="space-y-2">
              <h2 className="font-display text-base">Dead-letter (failed)</h2>
              {(q.data?.dead_letter ?? []).map((dl, i) => (
                <Card key={dl.id ?? i} className="flex flex-wrap items-center gap-4 justify-between text-sm">
                  <div className="min-w-0">
                    <div className="font-medium text-rose-700">{String(dl.original_name ?? dl.source_ref ?? 'unknown')}</div>
                    <div className="text-slate-500 mt-0.5">{String(dl.error ?? dl.reason ?? dl.message ?? '')}</div>
                  </div>
                  {dl.id && (
                    <div className="flex gap-2 shrink-0">
                      <button disabled={busy === dl.id} onClick={() => dlAct(dl.id as string, 'retry')}
                        className="px-3.5 py-1.5 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-100 text-sm font-medium disabled:opacity-50 transition-colors">
                        Retry
                      </button>
                      <button disabled={busy === dl.id} onClick={() => dlAct(dl.id as string, 'dismiss')}
                        className="px-3.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 text-sm font-medium disabled:opacity-50 transition-colors">
                        Dismiss
                      </button>
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
