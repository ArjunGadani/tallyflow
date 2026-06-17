// ---------------------------------------------------------------------------
// TallyFlow API client
// Lightweight fetch wrapper around the backend contract. Reads the base URL
// from VITE_API_BASE. When VITE_DEMO=true it serves bundled demo data so the
// dashboard renders without a backend.
// ---------------------------------------------------------------------------

import type {
  ActivityItem,
  ActivityResponse,
  ChatRequest,
  ChatResponse,
  FlowResponse,
  HealthResponse,
  IngestResponse,
  Invoice,
  InvoicesResponse,
  ReviewAction,
  ReviewQueue,
  Run,
  RunsResponse,
  Summary,
} from './types';
import { demo } from './demo';
import type { DateRange } from './components/DateRangeFilter';

/** Build a ?date_from=&date_to= query string from a range (empty -> ''). */
function rangeQS(range?: DateRange): string {
  const p = new URLSearchParams();
  if (range?.from) p.set('date_from', range.from);
  if (range?.to) p.set('date_to', range.to);
  const qs = p.toString();
  return qs ? '?' + qs : '';
}

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000';

export const DEMO_MODE: boolean =
  (import.meta.env.VITE_DEMO as string | undefined) === 'true';

/** A normalized error carrying the parsed backend message when available. */
export class ApiError extends Error {
  status: number;
  branch?: string;
  constructor(message: string, status: number, branch?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.branch = branch;
  }
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? 'GET',
      body: opts.body,
      signal: opts.signal,
      headers: opts.headers,
    });
  } catch (err) {
    // Network-level failure (server down, CORS, DNS, abort, etc.)
    if ((err as Error)?.name === 'AbortError') throw err;
    throw new ApiError(
      'Could not reach the TallyFlow server. Is the backend running?',
      0,
    );
  }

  const contentType = res.headers.get('content-type') ?? '';
  const isJson = contentType.includes('application/json');
  const payload: unknown = isJson ? await res.json().catch(() => null) : null;

  if (!res.ok) {
    // The contract returns { status, branch, message } on failure.
    const obj = (payload ?? {}) as Record<string, unknown>;
    const message =
      (typeof obj.message === 'string' && obj.message) ||
      `Request failed (${res.status})`;
    const branch = typeof obj.branch === 'string' ? obj.branch : undefined;
    throw new ApiError(message, res.status, branch);
  }

  return payload as T;
}

// ---------------------------------------------------------------------------
// Endpoint helpers
// ---------------------------------------------------------------------------

export const api = {
  /** Health probe for the cold-start poll. */
  async health(signal?: AbortSignal): Promise<HealthResponse> {
    if (DEMO_MODE) return { status: 'ok', service: 'tallyflow', version: 'demo' };
    // /api/healthz, not /healthz: Google Front End 404s a bare /healthz at the edge.
    return request<HealthResponse>('/api/healthz', { signal });
  },

  async summary(range?: DateRange, signal?: AbortSignal): Promise<Summary> {
    if (DEMO_MODE) return demo.summary;
    return request<Summary>(`/api/summary${rangeQS(range)}`, { signal });
  },

  async invoices(status?: string, range?: DateRange, signal?: AbortSignal): Promise<Invoice[]> {
    if (DEMO_MODE) {
      const all = demo.invoices;
      return status ? all.filter((i) => i.status === status) : all;
    }
    const p = new URLSearchParams();
    if (status) p.set('status', status);
    if (range?.from) p.set('date_from', range.from);
    if (range?.to) p.set('date_to', range.to);
    const qs = p.toString();
    const res = await request<InvoicesResponse>(`/api/invoices${qs ? '?' + qs : ''}`, { signal });
    return res.invoices ?? [];
  },

  /** Lean, prebuilt Activity feed — one round-trip, server-side derivation. */
  async activity(signal?: AbortSignal): Promise<ActivityItem[]> {
    if (DEMO_MODE) {
      return demo.invoices.map((i) => ({
        invoice_id: i.id, title: i.vendor_name ?? i.invoice_number ?? 'Document',
        branch: i.doc_type === 'non_invoice' ? 'non_invoice' : 'new',
        source: i.source ?? 'upload', status: i.status,
        last_step: i.events?.[i.events.length - 1]?.type ?? null,
        arrival: i.invoice_date ?? null, duration_ms: null,
        ts: i.invoice_date ?? null, total: i.total ?? null,
        currency: i.currency ?? null, base_total: i.base_total ?? null,
        base_currency: i.base_currency ?? null, error: null,
      }));
    }
    const res = await request<ActivityResponse>('/api/activity', { signal });
    return res.items ?? [];
  },

  async invoice(id: string, signal?: AbortSignal): Promise<Invoice> {
    if (DEMO_MODE) {
      const found = demo.invoices.find((i) => i.id === id);
      if (!found) throw new ApiError('Invoice not found', 404);
      return found;
    }
    return request<Invoice>(`/api/invoice/${encodeURIComponent(id)}`, { signal });
  },

  async deleteInvoice(id: string): Promise<{ status: string; id: string }> {
    if (DEMO_MODE) return { status: 'deleted', id };
    return request<{ status: string; id: string }>(`/api/invoice/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },

  async invoiceFlow(id: string, signal?: AbortSignal): Promise<FlowResponse> {
    if (DEMO_MODE) {
      const found = demo.invoices.find((i) => i.id === id);
      return { flow: found?.events ?? [] };
    }
    return request<FlowResponse>(`/api/invoice/${encodeURIComponent(id)}/flow`, {
      signal,
    });
  },

  async reviewQueue(signal?: AbortSignal): Promise<ReviewQueue> {
    if (DEMO_MODE) return demo.reviewQueue;
    return request<ReviewQueue>('/api/review-queue', { signal });
  },

  async review(id: string, action: ReviewAction): Promise<Invoice> {
    if (DEMO_MODE) {
      const updated = demo.applyReview(id, action);
      if (!updated) throw new ApiError('Invoice not found', 404);
      return updated;
    }
    const form = new FormData();
    form.append('action', action);
    return request<Invoice>(`/api/invoice/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      body: form,
    });
  },

  async reviewCount(signal?: AbortSignal): Promise<{ needs_review: number; dead_letter: number; total: number }> {
    if (DEMO_MODE) return demo.reviewCounts();
    return request('/api/review-count', { signal });
  },

  async retryDeadLetter(id: string): Promise<unknown> {
    if (DEMO_MODE) { demo.removeDeadLetter(id); return { branch: 'new', status: 'clean' }; }
    return request<unknown>(`/api/dead-letter/${encodeURIComponent(id)}/retry`, { method: 'POST' });
  },

  async dismissDeadLetter(id: string): Promise<unknown> {
    if (DEMO_MODE) { demo.removeDeadLetter(id); return { status: 'dismissed' }; }
    return request<unknown>(`/api/dead-letter/${encodeURIComponent(id)}/dismiss`, { method: 'POST' });
  },

  async runs(signal?: AbortSignal): Promise<Run[]> {
    if (DEMO_MODE) return demo.runs;
    const res = await request<RunsResponse>('/api/runs', { signal });
    return res.runs ?? [];
  },

  async triggerRun(): Promise<unknown> {
    if (DEMO_MODE) return { status: 'ok' };
    return request<unknown>('/api/run', { method: 'POST' });
  },

  async getSettings(signal?: AbortSignal): Promise<{ digest_enabled: boolean }> {
    if (DEMO_MODE) return { digest_enabled: true };
    return request<{ digest_enabled: boolean }>('/api/settings', { signal });
  },

  async setDigest(enabled: boolean): Promise<{ digest_enabled: boolean }> {
    if (DEMO_MODE) return { digest_enabled: enabled };
    const form = new FormData();
    form.append('digest_enabled', String(enabled));
    return request<{ digest_enabled: boolean }>('/api/settings', { method: 'POST', body: form });
  },

  async ingest(file: File, source?: string): Promise<IngestResponse> {
    if (DEMO_MODE) return demo.ingest(file);
    const form = new FormData();
    form.append('file', file);
    if (source) form.append('source', source);
    return request<IngestResponse>('/api/ingest', { method: 'POST', body: form });
  },

  /** TallyChat — grounded, read-only Q&A. JSON body (reuses the same wrapper). */
  async chat(req: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
    if (DEMO_MODE) return demo.chat(req);
    return request<ChatResponse>('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal,
    });
  },
};
