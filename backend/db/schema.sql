-- TallyFlow schema (§5). Apply to the reused Supabase Postgres project.
-- Money is NUMERIC(18,4) — exact decimal, never float. Enums are TEXT + CHECK
-- (easy to evolve as Groq/biz rules change). All timestamps are timestamptz.

create extension if not exists pgcrypto;  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- vendors: canonical vendor master + aliases for fuzzy normalization (§15)
-- ---------------------------------------------------------------------------
create table if not exists vendors (
    id               uuid primary key default gen_random_uuid(),
    canonical_name   text not null unique,
    aliases          text[] not null default '{}',
    default_category text,
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- invoices: one row per logical version of a document
-- ---------------------------------------------------------------------------
create table if not exists invoices (
    id                 uuid primary key default gen_random_uuid(),
    vendor_id          uuid references vendors(id),
    invoice_number     text,
    invoice_date       date,
    due_date           date,
    doc_type           text not null default 'invoice'
                         check (doc_type in ('invoice', 'credit_note', 'non_invoice')),
    currency           char(3),
    subtotal           numeric(18,4),
    tax_total          numeric(18,4),
    discount           numeric(18,4),
    shipping           numeric(18,4),
    total              numeric(18,4),
    -- base-currency conversion (deterministic, date-aware — §6, R15)
    base_currency      char(3),
    base_total         numeric(18,4),
    fx_rate            numeric(18,8),
    fx_date            date,
    category           text,
    status             text not null default 'received'
                         check (status in ('received','processing','extracted',
                           'needs_review','clean','stored','superseded','credited','failed')),
    version            int not null default 1,
    supersedes_id      uuid references invoices(id),
    credit_of_id       uuid references invoices(id),
    file_hash          text,
    source             text check (source in ('email','upload')),
    source_ref         text,                  -- msg-id / filename
    confidence_overall numeric(5,4),
    is_invoice         boolean not null default true,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create index if not exists idx_invoices_vendor_number on invoices (vendor_id, invoice_number);
create index if not exists idx_invoices_file_hash      on invoices (file_hash);
create index if not exists idx_invoices_status         on invoices (status);
-- Exact-duplicate guard (R5/idempotency): one stored row per file hash.
create unique index if not exists uq_invoices_file_hash on invoices (file_hash)
    where file_hash is not null;

create table if not exists line_items (
    id          uuid primary key default gen_random_uuid(),
    invoice_id  uuid not null references invoices(id) on delete cascade,
    description text,
    quantity    numeric(18,4),
    unit_price  numeric(18,4),
    amount      numeric(18,4)
);
create index if not exists idx_line_items_invoice on line_items (invoice_id);

create table if not exists tax_lines (
    id          uuid primary key default gen_random_uuid(),
    invoice_id  uuid not null references invoices(id) on delete cascade,
    label       text,                          -- GST / VAT / CGST / SGST ...
    rate        numeric(9,4),
    amount      numeric(18,4)
);
create index if not exists idx_tax_lines_invoice on tax_lines (invoice_id);

-- per-field confidence, display only (§5)
create table if not exists field_conf (
    invoice_id uuid not null references invoices(id) on delete cascade,
    field      text not null,
    confidence numeric(5,4),
    primary key (invoice_id, field)
);

create table if not exists invoice_files (
    id            uuid primary key default gen_random_uuid(),
    invoice_id    uuid not null references invoices(id) on delete cascade,
    storage_path  text not null,               -- Supabase Storage path (original retained)
    mime          text,
    pages         int,
    original_name text
);
create index if not exists idx_invoice_files_invoice on invoice_files (invoice_id);

-- full audit trail + drives the live processing-flow timeline (§9)
create table if not exists events (
    id         uuid primary key default gen_random_uuid(),
    seq        bigint generated always as identity,  -- stable insertion order (events in one txn share ts)
    invoice_id uuid references invoices(id) on delete cascade,
    ts         timestamptz not null default now(),
    type       text not null,                  -- received|classified|extracted|...
    detail     jsonb not null default '{}'::jsonb
);
create index if not exists idx_events_invoice_seq on events (invoice_id, seq);

create table if not exists processing_runs (
    id          uuid primary key default gen_random_uuid(),
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    source      text,
    processed   int not null default 0,
    skipped     int not null default 0,
    failed      int not null default 0
);

-- processed email message-ids — idempotent polling independent of the IMAP
-- read flag (opening mail in a client no longer causes a skip/reprocess).
create table if not exists processed_emails (
    message_id   text primary key,
    processed_at timestamptz not null default now()
);

-- documents that repeatedly failed — never silently dropped (§8, R-reliability)
create table if not exists dead_letter (
    id          uuid primary key default gen_random_uuid(),
    source_ref  text,
    file_hash   text,
    error       text,
    tries       int not null default 0,
    last_try    timestamptz,
    payload_path text                          -- stored raw payload for replay
);

-- small key/value app settings (e.g. digest_enabled) toggled from the dashboard
create table if not exists app_settings (
    key   text primary key,
    value text not null
);
