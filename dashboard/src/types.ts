// ---------------------------------------------------------------------------
// TallyFlow API type definitions
// Money fields are STRINGS on the wire (e.g. "120.00") to preserve precision.
// Parse with parseFloat only for display/charts.
// ---------------------------------------------------------------------------

/** Money is transported as a string to preserve decimal precision. */
export type Money = string;

/** ISO date / datetime string. */
export type ISODate = string;

export type DocType = 'invoice' | 'credit_note' | 'non_invoice';

export type InvoiceStatus =
  | 'received'
  | 'processing'
  | 'extracted'
  | 'needs_review'
  | 'clean'
  | 'stored'
  | 'superseded'
  | 'credited'
  | 'failed';

/** Routing branch decided by the pipeline. */
export type Branch =
  | 'new'
  | 'exact_duplicate'
  | 'logical_duplicate'
  | 'revision'
  | 'revision_late'
  | 'credit_note'
  | 'credit_orphan'
  | 'non_invoice'
  | 'dead_letter'
  | 'error';

/** Known pipeline event types (others may appear; treat as a string). */
export type EventType =
  | 'received'
  | 'type_detected'
  | 'classified'
  | 'extracted'
  | 'normalized'
  | 'validated'
  | 'confidence_scored'
  | 'vendor_matched'
  | 'categorized'
  | 'resolved'
  | 'currency_converted'
  | 'stored'
  | 'digest_queued'
  | 'exact_duplicate_reprocessed'
  | 'duplicate_linked'
  | 'review_decision'
  | 'currency_conversion_failed'
  | (string & {});

/** A pipeline event. `detail` is a loose bag of metadata keyed by event type. */
export interface FlowEvent {
  type: EventType;
  detail?: Record<string, unknown> | null;
  ts: ISODate;
}

export interface LineItem {
  description: string;
  quantity: Money | number;
  unit_price: Money;
  amount: Money;
}

export interface TaxLine {
  label: string;
  rate: Money | number;
  amount: Money;
}

export interface InvoiceFile {
  storage_path: string;
  mime: string;
  pages: number;
  original_name: string;
}

export interface Invoice {
  id: string;
  vendor_name: string;
  invoice_number: string;
  invoice_date: ISODate;
  due_date: ISODate | null;
  doc_type: DocType;
  currency: string;
  subtotal: Money;
  tax_total: Money;
  discount: Money;
  shipping: Money;
  total: Money;
  base_currency: string;
  base_total: Money;
  fx_rate: Money;
  fx_date: ISODate | null;
  category: string;
  status: InvoiceStatus;
  version: number;
  supersedes_id: string | null;
  credit_of_id: string | null;
  confidence_overall: number; // 0..1
  is_invoice: boolean;
  source?: string | null; // 'email' | 'upload'
  source_ref?: string | null;
  line_items: LineItem[];
  tax_lines: TaxLine[];
  events: FlowEvent[];
  files: InvoiceFile[];
}

export interface IngestResponse {
  invoice: Invoice | null;
  flow: FlowEvent[];
  branch: Branch;
  status: string;
  message: string;
}

export interface InvoicesResponse {
  invoices: Invoice[];
}

export interface FlowResponse {
  flow: FlowEvent[];
}

export interface Summary {
  base_currency: string;
  total_spend: Money;
  invoices_counted: number;
  credits_total: Money;
  pending_review_excluded: Money;
  needs_review_count: number;
  by_category: Record<string, Money>;
  by_vendor: Record<string, Money>;
}

export interface ReviewQueue {
  needs_review: Invoice[];
  dead_letter: DeadLetterItem[];
}

export interface ActivityItem {
  invoice_id: string | null;
  title: string;
  branch: string;
  source: string;
  status: string;
  last_step: string | null;
  arrival: ISODate | null;
  duration_ms: number | null;
  ts: ISODate | null;
  total: Money | null;
  currency: string | null;
  base_total: Money | null;
  base_currency: string | null;
  error: string | null;
}

export interface ActivityResponse {
  items: ActivityItem[];
}

export interface DeadLetterItem {
  id?: string;
  original_name?: string;
  reason?: string;
  message?: string;
  ts?: ISODate;
  [key: string]: unknown;
}

export interface Run {
  id?: string;
  started_at: ISODate;
  finished_at: ISODate | null;
  processed: number;
  skipped: number;
  failed: number;
  [key: string]: unknown;
}

export interface RunsResponse {
  runs: Run[];
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export type ReviewAction = 'approve' | 'dismiss';

// --- TallyChat (conversational assistant) ----------------------------------
export type ChatRole = 'user' | 'assistant';

export interface ChatToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result_source: string;
  ok: boolean;
}

export interface ResolvedRange {
  date_from: string | null;
  date_to: string | null;
  label: string;
}

/** Inline render card — built BY the backend from a typed tool output (never prose). */
export type ChatResultData =
  | { kind: 'summary'; data: Summary & { date_from?: string | null; date_to?: string | null } }
  | { kind: 'invoice'; data: Partial<Invoice> & { id: string } }
  | { kind: 'invoice_list'; data: Array<Record<string, unknown>>; truncated?: boolean };

export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
  history: { role: ChatRole; content: string }[];
}

export interface ChatResponse {
  conversation_id: string;
  answer: string | null;
  citations: string[];
  tool_trace: ChatToolCall[];
  result: ChatResultData | null;
  resolved_range: ResolvedRange | null;
  max_iterations_reached: boolean;
  grounding_ok: boolean;
}

/** A message in the local chat UI (superset of the wire response). */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  status: 'sending' | 'complete' | 'error';
  error?: string;
  citations?: string[];
  toolTrace?: ChatToolCall[];
  result?: ChatResultData | null;
  resolvedRange?: ResolvedRange | null;
  groundingOk?: boolean;
  maxIterations?: boolean;
  ts: string;
}
