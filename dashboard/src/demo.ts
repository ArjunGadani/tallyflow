// Optional offline demo data (VITE_DEMO=true) so the dashboard renders without
// a backend. Shapes mirror the API contract exactly.
import type {
  ChatRequest, ChatResponse, IngestResponse, Invoice, ReviewAction, ReviewQueue, Run, Summary,
} from './types';

const flow = (extra: Partial<Record<string, unknown>> = {}): Invoice['events'] => [
  { type: 'received', detail: {}, ts: '2026-05-10T09:00:00Z' },
  { type: 'type_detected', detail: { path: 'text' }, ts: '2026-05-10T09:00:01Z' },
  { type: 'classified', detail: { doc_type: 'invoice', confidence: 0.97 }, ts: '2026-05-10T09:00:02Z' },
  { type: 'extracted', detail: { path: 'text' }, ts: '2026-05-10T09:00:04Z' },
  { type: 'normalized', detail: { vendor: 'Globex Cloud', currency: 'GBP' }, ts: '2026-05-10T09:00:04Z' },
  { type: 'validated', detail: { totals_ok: true }, ts: '2026-05-10T09:00:05Z' },
  { type: 'confidence_scored', detail: { overall: 0.96 }, ts: '2026-05-10T09:00:05Z' },
  { type: 'vendor_matched', detail: { is_new: false }, ts: '2026-05-10T09:00:05Z' },
  { type: 'categorized', detail: { category: 'Cloud Hosting' }, ts: '2026-05-10T09:00:05Z' },
  { type: 'resolved', detail: { branch: 'new', ...extra }, ts: '2026-05-10T09:00:06Z' },
  { type: 'currency_converted', detail: { base_total: '120.00' }, ts: '2026-05-10T09:00:06Z' },
  { type: 'stored', detail: { branch: 'new', status: 'clean', version: 1 }, ts: '2026-05-10T09:00:06Z' },
  { type: 'digest_queued', detail: {}, ts: '2026-05-10T09:00:07Z' },
];

const inv = (over: Partial<Invoice>): Invoice => ({
  id: 'demo-1', vendor_name: 'Globex Cloud', invoice_number: 'INV-1001',
  invoice_date: '2026-05-01', due_date: '2026-05-31', doc_type: 'invoice',
  currency: 'GBP', subtotal: '100.00', tax_total: '20.00', discount: '0.00',
  shipping: '0.00', total: '120.00', base_currency: 'GBP', base_total: '120.00',
  fx_rate: '1', fx_date: '2026-05-01', category: 'Cloud Hosting', status: 'clean',
  version: 1, supersedes_id: null, credit_of_id: null, confidence_overall: 0.96,
  is_invoice: true,
  line_items: [{ description: 'Cloud hosting', quantity: '1', unit_price: '100.00', amount: '100.00' }],
  tax_lines: [{ label: 'VAT 20%', rate: '20', amount: '20.00' }],
  events: flow(), files: [{ storage_path: 'tallyflow-originals/demo-1/inv.pdf', mime: 'application/pdf', pages: 1, original_name: 'inv.pdf' }],
  ...over,
});

let invoices: Invoice[] = [
  inv({}),
  inv({ id: 'demo-2', vendor_name: 'Office Depot', invoice_number: 'INV-3001',
        currency: 'USD', total: '999.00', base_total: '789.21', fx_rate: '0.79',
        category: 'Office Supplies', status: 'needs_review', confidence_overall: 0.58 }),
  inv({ id: 'demo-3', vendor_name: 'Globex Cloud', invoice_number: 'CN-5001',
        doc_type: 'credit_note', total: '-20.00', base_total: '-20.00',
        status: 'credited', credit_of_id: 'demo-1', category: 'Cloud Hosting' }),
];

// Derive the summary from the CURRENT invoices using the same reconcile rules as
// the backend (skip superseded/non-invoice, subtract credits, exclude pending),
// so approving in Review actually moves the spend total — like production.
function computeSummary(): Summary {
  let total = 0, credits = 0, pending = 0, counted = 0, needsReview = 0;
  const byCat: Record<string, number> = {};
  const byVen: Record<string, number> = {};
  for (const i of invoices) {
    if (i.status === 'superseded') continue;
    if (i.doc_type === 'non_invoice' || i.is_invoice === false) continue;
    const bt = parseFloat(i.base_total) || 0;
    if (i.doc_type === 'credit_note') { const a = Math.abs(bt); credits += a; total -= a; continue; }
    if (i.status === 'needs_review' || i.status === 'failed') {
      pending += bt;
      if (i.status === 'needs_review') needsReview++;
      continue;
    }
    if (i.status === 'clean' || i.status === 'stored') {
      total += bt; counted++;
      const c = i.category || 'Uncategorized';
      const v = i.vendor_name || 'Unknown';
      byCat[c] = (byCat[c] || 0) + bt;
      byVen[v] = (byVen[v] || 0) + bt;
    }
  }
  const f = (n: number) => n.toFixed(2);
  const mapF = (m: Record<string, number>) =>
    Object.fromEntries(Object.entries(m).map(([k, v]) => [k, f(v)]));
  return {
    base_currency: 'GBP', total_spend: f(total), invoices_counted: counted,
    credits_total: f(credits), pending_review_excluded: f(pending), needs_review_count: needsReview,
    by_category: mapF(byCat), by_vendor: mapF(byVen),
  };
}

let reviewQueue: ReviewQueue = {
  needs_review: [invoices[1]],
  // Mirror the real /api/review-queue dead_letter shape exactly (id, source_ref, error).
  dead_letter: [{ id: 'dl-1', source_ref: 'broken.pdf', error: 'corrupt PDF', ts: '2026-05-10T08:00:00Z' }],
};

const runs: Run[] = [
  { id: 'run-1', started_at: '2026-05-10T09:00:00Z', finished_at: '2026-05-10T09:01:00Z', processed: 3, skipped: 1, failed: 0 },
];

let uploadSeq = 0;
function ingest(file: File): IngestResponse {
  // PERSIST the upload into the in-memory invoices so the total, the Invoices list,
  // and /invoice/:id all reflect it (otherwise uploads silently vanish + 404).
  uploadSeq += 1;
  const name = file.name.replace(/\.[^.]+$/, '') || 'Uploaded Vendor';
  const invoice = inv({ id: `demo-up-${uploadSeq}`, invoice_number: `INV-UP-${uploadSeq}`, vendor_name: name });
  invoices = [invoice, ...invoices];
  return { invoice, flow: invoice.events, branch: 'new', status: 'clean', message: `Processed ${file.name}` };
}

/** Scripted, keyword-matched chat — zero backend/LLM cost for the live demo.
 * Numbers come straight from the demo fixtures, so answers stay "grounded". */
async function chat(req: ChatRequest): Promise<ChatResponse> {
  await new Promise((r) => setTimeout(r, 450)); // let the typing indicator show
  const m = req.message.toLowerCase();
  const summary = computeSummary();
  const cur = summary.base_currency;
  const base: Omit<ChatResponse, 'answer' | 'citations' | 'tool_trace' | 'result'> = {
    conversation_id: req.conversation_id || 'demo-convo',
    resolved_range: null, max_iterations_reached: false, grounding_ok: true,
  };

  // Order matters: check the specific intents (review/duplicate) before the broad
  // spend match, so "review spending" routes to the review branch, not summary.
  if (/(review|pending|need)/.test(m)) {
    return {
      ...base,
      answer: `**${reviewQueue.needs_review.length}** invoice needs review and **${reviewQueue.dead_letter.length}** document failed processing.`,
      citations: ['review_queue'],
      tool_trace: [{ name: 'get_review_queue', arguments: {}, result_source: 'review_queue', ok: true }],
      result: { kind: 'invoice_list', data: reviewQueue.needs_review as unknown as Array<Record<string, unknown>> },
    };
  }
  if (/(duplicate|credit|revis)/.test(m)) {
    return {
      ...base,
      answer: `**INV-1001** from Globex Cloud (${cur} 120.00) has credit note **CN-5001** linked to it, reducing it by ${cur} 20.00. There's no duplicate version.`,
      citations: ['invoice:demo-1', 'invoice:demo-3'],
      tool_trace: [{ name: 'get_invoice', arguments: { invoice_id: 'demo-1' }, result_source: 'invoice:demo-1', ok: true }],
      result: { kind: 'invoice', data: { ...invoices[0], files: [] } },  // backend strips files from chat results
    };
  }
  if (/(spend|total|how much|summary|category|categories)/.test(m)) {
    return {
      ...base,
      answer: `Across all time you've spent **${cur} ${summary.total_spend}** on ${summary.invoices_counted} invoice, net of **${cur} ${summary.credits_total}** in credit notes. **${cur} ${summary.pending_review_excluded}** in ${summary.needs_review_count} invoice is excluded pending review.`,
      citations: ['summary'],
      tool_trace: [{ name: 'get_expense_summary', arguments: {}, result_source: 'summary', ok: true }],
      result: { kind: 'summary', data: { ...summary } },
    };
  }
  if (/(vendor)/.test(m)) {
    return {
      ...base,
      answer: `There are **2** vendors on record: Globex Cloud and Office Depot.`,
      citations: ['vendors'],
      tool_trace: [{ name: 'list_vendors', arguments: {}, result_source: 'vendors', ok: true }],
      result: null,
    };
  }
  return {
    ...base,
    answer: "I can answer questions about your spend, vendors, categories, duplicates, and the review queue — all from your processed invoices. Try “what did we spend?” or “which invoices need review?”.",
    citations: [], tool_trace: [], result: null,
  };
}

// Demo mutations so Approve/Dismiss/Retry visibly work without a backend.
function applyReview(id: string, action: ReviewAction): Invoice | null {
  const inv = invoices.find((i) => i.id === id) ?? null;
  // Match the backend review endpoint exactly: approve -> 'clean', dismiss -> 'failed'.
  const updated = inv ? { ...inv, status: action === 'approve' ? 'clean' : 'failed' } as Invoice : null;
  if (updated) invoices = invoices.map((i) => (i.id === id ? updated : i));
  reviewQueue = { ...reviewQueue, needs_review: reviewQueue.needs_review.filter((i) => i.id !== id) };
  return updated;
}

function removeDeadLetter(id: string): void {
  reviewQueue = { ...reviewQueue, dead_letter: reviewQueue.dead_letter.filter((d) => d.id !== id) };
}

function reviewCounts() {
  const nr = reviewQueue.needs_review.length;
  const dl = reviewQueue.dead_letter.length;
  return { needs_review: nr, dead_letter: dl, total: nr + dl };
}

// Getters so callers always read the CURRENT (mutated) state, not a stale snapshot.
export const demo = {
  get summary() { return computeSummary(); },
  get invoices() { return invoices; },
  get reviewQueue() { return reviewQueue; },
  get runs() { return runs; },
  ingest, chat, applyReview, removeDeadLetter, reviewCounts,
};
