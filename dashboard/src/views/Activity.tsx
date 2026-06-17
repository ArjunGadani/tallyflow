import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { AmountWithBase } from '../components/AmountWithBase';
import { Card } from '../components/Card';
import { Skeleton } from '../components/Skeleton';
import type { ActivityItem } from '../types';
import { BRANCH_LABEL, fmtDateTime, stepLabel } from '../utils';

function durationLabel(ms?: number | null): string {
  if (ms == null || ms < 0) return '';   // 0ms is a valid (sub-ms) duration
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const BRANCH_DOT: Record<string, string> = {
  new: 'bg-emerald-500', revision: 'bg-sky-500', revision_late: 'bg-amber-500',
  credit_note: 'bg-sky-500', credit_orphan: 'bg-amber-500',
  exact_duplicate: 'bg-slate-400', logical_duplicate: 'bg-slate-400',
  non_invoice: 'bg-slate-300', dead_letter: 'bg-rose-500',
};

export function Activity() {
  const [rows, setRows] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [showNonInvoice, setShowNonInvoice] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string>('');
  const nav = useNavigate();
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const items = await api.activity();
        if (!active) return;
        setRows(items);
        setErr(null);
        setLoading(false);
        setUpdatedAt(new Date().toLocaleTimeString());
      } catch (e) {
        if (active) { setErr((e as Error).message); setLoading(false); }
      }
    };
    void load();
    // Poll only while live AND the tab is visible — a backgrounded tab shouldn't
    // hammer the feed (each poll is a full DB read).
    const id = window.setInterval(() => {
      if (liveRef.current && document.visibilityState === 'visible') void load();
    }, 3000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const hiddenCount = rows.filter((r) => r.branch === 'non_invoice').length;
  const visible = showNonInvoice ? rows : rows.filter((r) => r.branch !== 'non_invoice');

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl">Activity</h1>
          <p className="text-sm text-slate-500 mt-1">Every document the pipeline processed — uploads and email — updating live.</p>
        </div>
        <button onClick={() => setLive((v) => !v)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 text-sm font-medium text-slate-600 hover:bg-slate-100">
          <span className={`h-2 w-2 rounded-full ${live ? 'bg-emerald-500 animate-pulse' : 'bg-slate-300'}`} />
          {live ? `Live · ${updatedAt}` : 'Paused'}
        </button>
      </div>

      {err && <div className="bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium">{err}</div>}

      {loading ? (
        <Skeleton className="h-64" />
      ) : (
        <Card className="p-0 divide-y divide-slate-100">
          {visible.length === 0 && <div className="p-5 text-sm text-slate-400">No activity yet — upload an invoice or run the inbox poll.</div>}
          {visible.map((r) => (
            <div
              key={r.invoice_id ?? `dl-${r.ts ?? ''}-${r.title}`}
              onClick={() => r.invoice_id && nav(`/invoice/${r.invoice_id}`)}
              className={`flex items-center gap-3 px-4 py-3 ${r.invoice_id ? 'cursor-pointer hover:bg-slate-50' : ''}`}
            >
              <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${BRANCH_DOT[r.branch] ?? 'bg-slate-300'}`} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-slate-800 text-sm truncate">{r.title}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{r.source}</span>
                </div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {BRANCH_LABEL[r.branch as keyof typeof BRANCH_LABEL] ?? r.branch}
                  {r.last_step ? ` · ${stepLabel(r.last_step)}` : ''}
                  {r.duration_ms != null && r.duration_ms >= 0 ? <span className="text-emerald-600"> · processed in {durationLabel(r.duration_ms)}</span> : null}
                  {r.error && <span className="text-rose-500"> · {r.error}</span>}
                </div>
              </div>
              {r.total != null && (
                <div className="hidden sm:block shrink-0">
                  <AmountWithBase total={r.total} currency={r.currency}
                    baseTotal={r.base_total} baseCurrency={r.base_currency} size="sm" align="right" />
                </div>
              )}
              <div className="text-xs text-slate-400 tnum shrink-0 w-36 text-right hidden md:block">
                <div>arrived</div>
                <div>{fmtDateTime(r.arrival || r.ts)}</div>
              </div>
            </div>
          ))}
          {hiddenCount > 0 && (
            <button onClick={() => setShowNonInvoice((v) => !v)}
              className="w-full px-4 py-2.5 text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 text-left">
              {showNonInvoice
                ? `Hide ${hiddenCount} non-invoice${hiddenCount > 1 ? 's' : ''} (promos, newsletters)`
                : `${hiddenCount} non-invoice${hiddenCount > 1 ? 's' : ''} hidden · Show`}
            </button>
          )}
        </Card>
      )}
    </div>
  );
}
