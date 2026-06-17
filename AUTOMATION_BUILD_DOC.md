# Build Document — Project 3: "TallyFlow" (Invoice Extraction & Expense Automation)
## Production-grade spec — built as a real tool, not a demo

> Hand this entire file to Claude Code. Read it fully, restate the architecture, flag risks, propose a build plan, and wait for approval before coding. This is scoped as a real-world AP (accounts-payable) automation tool. The hard part is NOT extraction — it's the business logic around duplicates, revisions, credit notes, currency, reconciliation, reliability, and trust. Treat that as first-class.

---

## 0. Design philosophy

Invoice extraction is ~10% of the value. The other 90% is handling the hundreds of messy real-world situations correctly and never silently producing a wrong number. The tool must be:
- **Idempotent** — reprocessing the same input never double-counts.
- **Trustworthy** — anything uncertain is flagged, not silently accepted.
- **Auditable** — every invoice keeps its original file + a full event history.
- **Resilient** — LLM/API failures are retried, never lost.

### Where the LLM is used vs deterministic code (critical boundary — respect strictly)
The LLM is used ONLY for understanding messy input. All money math, matching, and decisions are deterministic code. Never let the LLM decide duplicates/revisions or do arithmetic — that is where hallucination corrupts the numbers.

LLM is used in exactly three places:
1. **Classification** — invoice / credit_note / non_invoice (small fast model; vision model if image-only). Filters junk before extraction.
2. **Extraction** (core) — pull structured fields into JSON. Text path -> strong text model (llama-3.3-70b-versatile); scanned/image path -> vision model (llama-4-scout).
3. **Categorization** — infer expense category from vendor + line items (preferably folded INTO the extraction JSON to save a call; tiny separate call otherwise).

The LLM is explicitly NOT used for (these are plain code):
- File hashing / exact-duplicate detection
- Dedup / revision / credit-note resolution (section 6) — deterministic rules only
- Date / number / currency normalization
- Totals / tax reconciliation math
- Currency conversion
- Vendor fuzzy-matching (string similarity, not LLM)

Model IDs (classification, text-extraction, vision-extraction) MUST be env-config strings in ONE place, not hardcoded across files, since Groq rotates models frequently. Optionally validate the configured models against https://api.groq.com/openai/v1/models at startup and warn if any is no longer active.

### Automation vs human oversight (resolved decision)
Default is fully automated: no manual field-editing/correction workflow. BUT the tool assigns each invoice a **status** and flags low-confidence / anomalous / ambiguous ones as needs_review. The dashboard surfaces these. This is display + simple state transitions, NOT a correction editor. Rationale: a real tool that silently accepts bad extractions destroys client trust; flagging is the minimum viable safety net.

---

## 1. What we are building

An automated accounts-payable tool. Invoices and receipts arrive (primarily by email, also dashboard upload), are read, structured, validated, de-duplicated, reconciled against prior versions, categorized, stored with a full audit trail, and summarized in scheduled email + Slack digests — all viewable in a dashboard that also shows the live processing flow per document.

---

## 2. Real-world scenario catalogue (handle ALL of these)

This is the core of the spec. Each scenario needs explicit handling.

### A. Ingestion-level
1. **Exact duplicate file** — same attachment emailed twice -> detect via file hash, link to original, do not reprocess or double-count.
2. **Logical duplicate** — same invoice arriving as a different file (re-scan, re-export) -> detect via (vendor + invoice_number + total + date) match -> link, don't double-count.
3. **Revised / corrected invoice** — same vendor + invoice_number, but changed amount/line items/date -> treat as a new version that supersedes the prior; keep both; expense reflects the latest; mark old superseded.
4. **Credit note / credit memo** — explicit credit, or negative total, often referencing an original invoice -> reduces expense; link to the referenced invoice; never treat as a normal positive invoice.
5. **Multiple invoices in one PDF/email** -> split and process each separately.
6. **One invoice split across multiple files/pages/emails** -> combine before extraction.
7. **Invoice in the email body** (no attachment) -> extract from body text.
8. **Forwarded email with nested attachments** -> unwrap and find the actual invoice.
9. **Non-invoice attachments** — logos, signatures, T&C pages, marketing, calendar invites -> classify and skip (is_invoice=false), don't store as expense.
10. **Password-protected / corrupted / unsupported files** -> flag, log, skip gracefully, notify in digest.
11. **Huge / many-page files** -> page-split, compress under Groq's 4 MB / 5-image limits.

### B. Document/image quality
12. **Scanned, rotated, skewed, low-contrast, glare, partial** photos -> vision path; pre-process (auto-rotate, downscale, enhance) before sending.
13. **Mixed digital + scanned** in one doc -> per-page detection.
14. **Handwritten amounts / notes** -> low confidence, flag for review.

### C. Data/extraction-level
15. **Vendor name variants** — "Amazon", "Amazon Web Services", "AWS EMEA SARL" -> normalize to a canonical vendor (vendor master + fuzzy match).
16. **Multiple tax lines** — GST/VAT split (CGST+SGST, multiple rates) -> capture as a tax breakdown, not a single number.
17. **Discounts, shipping, fees, rounding** -> capture; reconcile totals with tolerance.
18. **Totals that don't add up** -> flag mismatch, lower confidence, needs_review.
19. **Ambiguous dates** (DD/MM vs MM/DD) -> use locale/currency/context hints; flag if unresolved.
20. **Multi-currency / foreign currency** -> capture original currency + amount; convert to a configured base currency using a stored FX rate (date-aware); keep both.
21. **Missing fields** (no invoice number, no date) -> null + fallback matching keys; flag.
22. **Line items spanning pages** -> stitch.

### D. Business-logic / lifecycle
23. **Status lifecycle:** received -> processing -> extracted -> (needs_review | clean) -> stored -> superseded/credited (+ failed).
24. **Confidence thresholds** route to needs_review (configurable).
25. **Vendor master & categorization rules** — learned/explicit mapping vendor->category, overrideable by rules.
26. **Audit trail** — every state change is an event (timestamp, actor=system, detail); original file retained.
27. **Reconciliation** — expense totals always reflect: latest version of each invoice, minus credit notes, deduped, in base currency.

### E. Reliability/ops
28. **LLM rate-limit / transient error** -> retry with backoff; if still failing -> dead-letter + flag, never lose the doc.
29. **Partial extraction** -> store what's valid, flag the rest.
30. **Reprocessing / replay** -> idempotent (file hash + logical keys prevent dupes).
31. **Poison message** (always fails) -> dead-letter after N tries, surfaced in digest.

---

## 3. Architecture

```
INGRESS
  - Email inbox (IMAP poll, scheduled)  -- primary, production-realistic
  - Dashboard upload                    -- secondary / manual

PROCESSING PIPELINE (FastAPI on Cloud Run service, free shared tier)
  unwrap email/attachments -> file hash (exact-dup check)
   -> classify (invoice? credit note? non-invoice?)
   -> split (multi-invoice) / combine (multi-file)
   -> per-page type detect (digital vs scanned)
   -> EXTRACT (text path | Groq vision path) -> strict JSON
   -> normalize + validate (dates, currency, tax, totals)
   -> confidence scoring -> status (clean | needs_review)
   -> vendor normalization + categorization
   -> DEDUP / REVISION / CREDIT-NOTE resolution (logical keys)
   -> currency conversion to base
   -> STORE (invoice + line items + tax + events) in Supabase
   -> emit processing events (for live flow view)

ASYNC / RELIABILITY
   -> retry queue + backoff; dead-letter on repeated failure

SCHEDULED (GitHub Actions cron)
   -> poll inbox -> run pipeline -> send Email + Slack digest

DASHBOARD (React, playful-modern)
   -> invoices, expense charts, per-doc LIVE PROCESSING FLOW, needs-review queue
```

Cloud Run free tier is per billing account, shared across all services — this coexists with the user's existing GCP service for free, provided all services use min-instances=0 (scale to zero) and are not pinged 24/7. $1 budget alert required.

---

## 4. Tech stack (locked)

| Layer | Choice |
|---|---|
| Extraction (scanned/image) | Groq vision meta-llama/llama-4-scout-17b-16e-instruct, JSON mode |
| Extraction (digital PDF) | text extract (pdfplumber/pypdf) -> Groq text llama-3.3-70b-versatile, JSON mode |
| Classification | lightweight Groq call: invoice / credit_note / non_invoice |
| Image preprocessing | Pillow/OpenCV (auto-rotate, downscale <4MB, enhance) |
| Backend | Python FastAPI -> Cloud Run (free, scale-to-zero, US free region) |
| Storage | Supabase (Postgres) — reuse an existing project with dedicated tables (2-project free limit) |
| Original file storage | Supabase Storage (free tier) — retain originals for audit |
| FX rates | a free FX rate source cached daily (or a static table) for base-currency conversion |
| Delivery | Email (SMTP / Resend free) + Slack incoming webhook |
| Scheduling | GitHub Actions cron |
| Dashboard | React (Vite) + Tailwind + Framer Motion + Recharts |

### Groq vision constraints
Max 4 MB/base64 image (else 413), max 5 images/request, temperature 0, JSON mode + strict schema.

---

## 5. Data model (Supabase)

```
vendors        (id, canonical_name, aliases[], default_category, created_at)
invoices       (id, vendor_id, invoice_number, invoice_date, due_date,
                doc_type [invoice|credit_note], currency, subtotal, tax_total,
                discount, shipping, total,
                base_currency, base_total, fx_rate, fx_date,
                category, status [received|processing|extracted|needs_review|
                  clean|stored|superseded|credited|failed],
                version, supersedes_id (nullable), credit_of_id (nullable),
                file_hash, source [email|upload], source_ref (msg-id/filename),
                confidence_overall, is_invoice (bool), created_at, updated_at)
line_items     (id, invoice_id, description, quantity, unit_price, amount)
tax_lines      (id, invoice_id, label [GST/VAT/CGST...], rate, amount)
field_conf     (invoice_id, field, confidence)        -- per-field, display only
invoice_files  (id, invoice_id, storage_path, mime, pages, original_name)
events         (id, invoice_id, ts, type, detail)     -- full audit trail + live flow
processing_runs(id, started_at, finished_at, source, processed, skipped, failed)
dead_letter    (id, source_ref, file_hash, error, tries, last_try, payload_path)
```

Indexes: (vendor_id, invoice_number), file_hash, status.
Dedup/revision keys: exact = file_hash; logical = (vendor_id, invoice_number), fallback fuzzy (vendor_id, invoice_date, total).

---

## 6. Dedup / revision / credit-note resolution (the heart of it)

On each newly extracted invoice, before final store:
1. **Exact duplicate?** file_hash already seen -> link, increment, stop (no expense impact).
2. **Credit note?** doc_type=credit_note or negative total -> find referenced invoice (by referenced number/vendor); store as credit_of_id, status credited; expense logic subtracts it.
3. **Logical match exists?** same (vendor_id, invoice_number):
   - identical totals/lines/date -> logical duplicate -> link, stop.
   - different totals/lines/date -> revision: new row, version = old.version+1, supersedes_id = old.id; mark old superseded; latest wins in expense.
4. **No invoice_number** -> fuzzy match (vendor, date, total); if strong match -> treat as dup/revision per above; else new.
5. Else -> brand-new invoice.

All outcomes write an event (audit + drives the live flow view). Expense/reporting queries ALWAYS compute over: latest non-superseded invoices, minus credit notes, deduped, in base currency.

---

## 7. Extraction + validation

- Classify first (invoice / credit_note / non_invoice). Non-invoice -> flag, skip.
- Detect digital vs scanned per page; route to text or vision path.
- Strict JSON schema (vendor, numbers, dates, currency, line_items[], tax_lines[], plus references for credit notes). null for missing; never fabricate.
- Normalize: dates->ISO (locale-aware, flag ambiguous), numbers->decimal, currency->ISO code, vendor->canonical.
- Validate: subtotal - discount + tax + shipping ~= total within tolerance; tax lines sum to tax_total; line items sum to subtotal. Mismatch -> lower confidence + needs_review.
- Confidence: combine model-reported + validation heuristics -> per-field + overall. Below threshold -> needs_review.

### Extraction prompt (strict JSON-only) — implement as specified
```
You are an accounts-payable extraction engine. From the provided document,
return ONLY a JSON object matching the schema. Rules:
- First determine doc_type: "invoice", "credit_note", or "non_invoice".
- Use null for any field not present. NEVER guess or fabricate.
- Dates YYYY-MM-DD; if format is ambiguous, return best guess and set its
  confidence low. Numbers as plain decimals, no symbols. Currency as ISO code.
- Capture every line item and every tax line separately.
- For a credit note, capture the referenced invoice number if present.
- Provide a 0..1 confidence for each top-level field in "_confidence".
- Output nothing except the JSON object.
Schema: { doc_type, vendor_name, vendor_address, invoice_number,
  referenced_invoice_number, invoice_date, due_date, currency, subtotal,
  discount, shipping, tax_lines:[{label,rate,amount}], tax_total, total,
  line_items:[{description,quantity,unit_price,amount}], _confidence:{...} }
```

---

## 8. Reliability

- Each document = a job with status + try-count. Transient failures (Groq 429/5xx, network) -> exponential backoff retry.
- After N retries -> dead_letter with the stored payload; surfaced in the digest; never silently dropped.
- Idempotency via file_hash + logical keys — safe to replay any run.
- processing_runs records each scheduled run's counts (processed/skipped/failed).

---

## 9. Live processing flow (dashboard feature — requested)

Every document exposes its pipeline as an ordered, animated timeline driven by the events table:
```
Received -> Classified (invoice/credit/non) -> Type detected (digital/scanned)
-> Extracted (text/vision) -> Normalized -> Validated (totals ok/mismatch)
-> Confidence scored -> Vendor matched -> Categorized
-> Dedup/Revision resolved (new / duplicate / revision v2 / credit note)
-> Currency converted -> Stored -> Digest queued
```
Each step shows state (pending/active/done/failed/skipped), a sub-detail line (e.g. "Scanned image -> vision model", "Matched existing INV-1042 -> revision v2 supersedes v1", "Totals mismatch -> needs review"), and timing. A run-history view shows per-run summaries. This makes the automation visible and is a major portfolio differentiator.

---

## 10. Delivery (Email + Slack digest)
Scheduled digest summarizing the run: invoices processed, total spend (base currency, net of credits), by category/vendor/top-N, FX note, duplicates/revisions detected, needs_review count, failures/dead-letter count, link to dashboard. Sent to BOTH email (HTML) and Slack (blocks). Consistent with stored data.

---

## 11. Backend API (FastAPI, Cloud Run)
- GET /healthz — pure 200, no DB/LLM (boot + startup probe).
- POST /api/ingest — upload a file -> run full pipeline -> return invoice + flow events.
- GET /api/invoices?status=&from=&to=&vendor=&category= — list (filterable).
- GET /api/invoice/{id} — detail (fields, confidence, line/tax, versions, events, file preview URL).
- GET /api/invoice/{id}/flow — ordered processing events for the timeline.
- GET /api/summary?from=&to= — reconciled expense summary (latest versions - credits, base currency).
- GET /api/review-queue — invoices with status needs_review / failed / dead-letter.
- POST /api/run — trigger inbox poll + pipeline + digest (callable by cron).
Secrets from env only; never logged. Lazy-init, reuse connections. Graceful errors. CORS to dashboard origin.

### Cloud Run deploy
US free region (us-central1/us-east1/us-west1), min-instances=0, max-instances low (cost guard), --allow-unauthenticated. Shared free tier across the account; do NOT 24/7-ping multiple services. $1 GCP budget alert. Document the exact gcloud run deploy in README.

---

## 12. Dashboard — "playful modern" (third distinct identity)

Distinct from P1 (dark-minimal) and P2 (light-vivid editorial): rounded, friendly, pastel-but-confident.
- Generous radius (rounded-3xl, pills), soft lively surfaces, pastel base (mint/lilac/peach/sky) + confident saturated accents.
- Rounded friendly sans; clear number styling for amounts.
- Framer Motion: spring micro-interactions, cards pop in, count-ups, a satisfying "processed" reveal, the flow timeline animating step-by-step.

Views:
1. **Overview** — summary cards (Total Spend net of credits, Invoices Processed, Avg/Invoice, Needs Review count, Top Category), expense charts (over time, by category donut, by vendor bar) with date filter.
2. **Invoices** — friendly list/cards: vendor, date, total, currency, category chip, status badge, confidence ring (display only). Filters incl. status. Click -> detail.
3. **Invoice detail** — extracted fields + per-field confidence, line items, tax breakdown, version history (v1/v2/superseded, credit links), the live processing flow timeline, and the original document preview side-by-side.
4. **Review queue** — needs_review / failed / dead-letter surfaced (display + status; no field-editing).
5. **Upload** — drag-drop with the animated processing flow, then result reveal.
6. **Runs** — scheduled-run history (counts, duplicates/revisions/credits/failures).

Boot state polls /healthz (covers Cloud Run cold start). Skeleton loaders. Optional static-JSON demo fallback.

---

## 13. Data source (demo data, realistic)
A generator script produces varied realistic-but-fake documents to exercise EVERY scenario in section 2:
- Digital PDFs + "scanned" images (rotated/noisy) — both extraction paths.
- Varied layouts, vendors, multi-currency, multi-tax (GST/VAT), discounts/shipping.
- Deliberate hard cases: an exact-duplicate file, a logical duplicate, a revised invoice (v2 with changed total), a credit note, a multi-invoice PDF, a non-invoice attachment, a totals-mismatch invoice, an ambiguous-date invoice, a foreign-currency invoice, a corrupt file.
- Plus the email inbox as the live source: forward any of these to the watched inbox to demo the real flow.
No real/private invoices in the repo (privacy). Your own real invoices: local demo only, never committed.

---

## 14. Repo structure
```
tallyflow/
  backend/
    main.py            # FastAPI + endpoints
    pipeline.py        # orchestrates the full flow + event emission
    classify.py        # invoice/credit/non-invoice
    extract.py         # type detect, text+vision paths, Groq, schema
    preprocess.py      # image rotate/downscale/enhance, page split
    normalize.py       # dates/currency/numbers/vendor normalization
    validate.py        # totals/tax reconciliation + confidence
    resolve.py         # dedup / revision / credit-note logic (section 6)
    fx.py              # base-currency conversion (cached rates)
    ingest_email.py    # IMAP unwrap + attachments + body
    digest.py          # email + slack
    store.py           # Supabase CRUD + Storage + events
    retry.py           # backoff + dead-letter
    schema.py          # pydantic models
    requirements.txt
    Dockerfile
  dashboard/           # React app
  generator/           # realistic test-document generator (section 13)
  sample_docs/         # generated fixtures incl. all hard cases
  .github/workflows/automation.yml   # cron: poll + pipeline + digest
  .env.example
  .gitignore
  README.md
```

---

## 15. Setup checklist
1. **Groq** — existing key (vision + text, same free tier).
2. **Supabase** — reuse an existing project; add tables (section 5) + a Storage bucket for originals (mind 2-project free limit).
3. **Slack** — incoming webhook -> SLACK_WEBHOOK.
4. **Email** — Gmail app password (IMAP receive + SMTP send) or Resend free for sending.
5. **GCP/Cloud Run** — deploy in US free region, scale-to-zero; $1 budget alert; coexists free with the user's existing GCP service.
6. **GitHub** — repo + Actions secrets (Groq, Supabase, IMAP, SMTP/Resend, Slack).
7. **FX** — pick a free rate source or ship a static rate table.

---

## 16. Build order
1. Backend skeleton + /healthz + Supabase schema (section 5) + Storage bucket.
2. Extraction core: classify, type-detect, text + vision paths, strict JSON, on sample_docs/.
3. Normalize + validate + confidence + status.
4. Resolve engine (section 6): dedup / revision / credit-note, with events.
5. FX conversion + reconciled summary query.
6. POST /api/ingest end-to-end (incl. file hash, originals to Storage, events).
7. Retry + dead-letter.
8. Email ingestion (IMAP unwrap/attachments/body, dedup).
9. Digest (email + Slack).
10. GitHub Actions cron (poll + pipeline + digest) + processing_runs.
11. Generator producing all section 2 hard cases.
12. Dashboard: playful-modern theme; Overview; Invoices + detail (with version history + live flow timeline + doc preview); Review queue; Upload w/ animated flow; Runs.
13. Dockerfile + Cloud Run deploy (free region, scale-to-zero, $1 budget alert).
14. README (+ "how this maps to a real client AP deployment": swap generator/inbox for the client's real invoice inbox; same pipeline).

### Acceptance checks (must pass)
- Digital PDF -> text path; scanned/rotated image -> vision path (auto-rotated, <4MB).
- Exact-duplicate file detected (hash) -> no double-count.
- Logical duplicate detected -> no double-count.
- Revised invoice -> v2 supersedes v1; expense reflects v2; both retained; event logged.
- Credit note -> linked to original; expense reduced.
- Multi-invoice PDF -> split into separate invoices.
- Non-invoice attachment -> flagged, not stored as expense.
- Totals-mismatch / ambiguous-date / handwritten -> needs_review.
- Multi-currency invoice -> original + base-currency stored with FX rate.
- Multi-tax (GST/VAT) -> tax_lines captured separately.
- Groq failure -> retried, then dead-lettered, surfaced in digest, never lost.
- Reprocessing a run double-counts nothing (idempotent).
- Dashboard shows per-document live processing flow with correct branch (new/dup/revision/credit).
- Reconciled summary = latest versions - credits, deduped, base currency.
- Scheduled run polls inbox, processes, sends Email + Slack digest, records the run.
- Cloud Run: free region, scale-to-zero, coexists with existing GCP service; $1 budget alert set. No secrets committed/logged.