// Display helpers (formatting + label/colour maps). Pure, UI-only.
import type { Branch, FlowEvent, InvoiceStatus } from './types';

export function toNumber(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isNaN(n) ? 0 : n;
}

export function fmtMoney(v: string | number | null | undefined, currency?: string): string {
  const s = toNumber(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${currency} ${s}` : s;
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

export function fmtDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// Refined badge styles: subtle tinted bg + ring + saturated text.
export const STATUS_STYLES: Record<InvoiceStatus, string> = {
  received: 'bg-slate-50 text-slate-600 ring-1 ring-slate-200',
  processing: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200',
  extracted: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200',
  needs_review: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  clean: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  stored: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  superseded: 'bg-slate-50 text-slate-400 ring-1 ring-slate-200 line-through',
  credited: 'bg-sky-50 text-sky-700 ring-1 ring-sky-200',
  failed: 'bg-rose-50 text-rose-700 ring-1 ring-rose-200',
};

export const STATUS_LABEL: Record<InvoiceStatus, string> = {
  received: 'Received',
  processing: 'Processing',
  extracted: 'Extracted',
  needs_review: 'Needs review',
  clean: 'Clean',
  stored: 'Stored',
  superseded: 'Superseded',
  credited: 'Credited',
  failed: 'Failed',
};

export const BRANCH_LABEL: Record<Branch, string> = {
  new: 'New invoice',
  exact_duplicate: 'Exact duplicate',
  logical_duplicate: 'Logical duplicate',
  revision: 'Revision (supersedes prior)',
  revision_late: 'Late older version',
  credit_note: 'Credit note',
  credit_orphan: 'Credit (unlinked)',
  non_invoice: 'Non-invoice',
  dead_letter: 'Dead-lettered',
  error: 'Error',
};

// Friendly labels for the live processing-flow timeline (§9).
const STEP_LABELS: Record<string, string> = {
  received: 'Received',
  type_detected: 'Type detected',
  classified: 'Classified',
  extracted: 'Extracted',
  normalized: 'Normalized',
  validated: 'Validated',
  confidence_scored: 'Confidence scored',
  vendor_matched: 'Vendor matched',
  categorized: 'Categorized',
  resolved: 'Dedup / revision resolved',
  currency_converted: 'Currency converted',
  stored: 'Stored',
  digest_queued: 'Digest queued',
  exact_duplicate_reprocessed: 'Exact duplicate (reprocessed)',
  duplicate_linked: 'Linked to existing',
  review_decision: 'Review decision',
  currency_conversion_failed: 'Currency conversion failed',
};

export function stepLabel(type: string): string {
  return STEP_LABELS[type] ?? type.replace(/_/g, ' ');
}

// A short, human sub-detail line derived from an event's detail bag.
export function stepDetail(ev: FlowEvent): string {
  const d = (ev.detail ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case 'type_detected':
      return d.path === 'vision' ? 'Scanned image → vision model' : 'Digital text → text model';
    case 'classified':
      return `${d.doc_type ?? ''}`.trim();
    case 'extracted':
      return d.path === 'vision' ? 'via vision model' : 'via text model';
    case 'normalized':
      return [d.vendor, d.currency].filter(Boolean).join(' · ');
    case 'validated':
      return d.totals_ok === false ? 'Totals mismatch → review' : 'Totals reconcile';
    case 'confidence_scored':
      return typeof d.overall === 'number' ? `${Math.round((d.overall as number) * 100)}%` : '';
    case 'categorized':
      return `${d.category ?? ''}`;
    case 'resolved':
      return BRANCH_LABEL[(d.branch as Branch)] ?? `${d.branch ?? ''}`;
    case 'currency_converted':
      return d.base_total ? `→ ${d.base_total}` : '';
    case 'stored':
      return d.branch ? `${d.branch}${d.version ? ` v${d.version}` : ''}` : '';
    default:
      return '';
  }
}

export function isFailedStep(type: string): boolean {
  return type.includes('failed');
}

// Shared chart palette + compact axis formatter (used by Overview and TallyChat's
// inline result cards, so both render identically from one source).
export const CHART_COLORS = ['#059669', '#0ea5e9', '#f59e0b', '#64748b', '#14b8a6', '#e11d48', '#8b5cf6', '#f97316'];

/** Compact number: 21286 -> "21.3k", 1_200_000 -> "1.2M". */
export function nfmt(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(Math.round(n));
}
