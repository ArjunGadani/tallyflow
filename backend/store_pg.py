"""Production store: Postgres (Supabase) via psycopg, mirroring LocalStore.

Atomic writes go through the store_invoice() SQL function (R5) — the one place
the invoice + children + events + supersede-mark commit together. Reads are
plain SQL (psycopg returns Decimal/date/jsonb natively). Originals are uploaded
to Supabase Storage when configured, else kept locally as a fallback.
"""
from __future__ import annotations

import os
import uuid as _uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from backend.store import ACTIVITY_FEED_LIMIT


def _is_uuid(value) -> bool:
    """Guard id lookups: a non-UUID id would make Postgres raise on the uuid
    column (-> 500). Returning None for a bad id yields a clean 404 instead."""
    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False

from backend.config import get_settings
from backend.store import Store


def _payload(d: dict) -> dict:
    """Stringify Decimals/dates so the value is JSON-serialisable; the SQL
    function casts text -> numeric/date."""
    out = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, (date, datetime)):
            out[k] = v.isoformat()
        elif isinstance(v, bool):
            out[k] = v
        else:
            out[k] = v
    return out


class PgStore(Store):
    def __init__(self, dsn: Optional[str] = None):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        s = get_settings()
        self._dsn = dsn or s.supabase_db_url
        if not self._dsn:
            raise RuntimeError("SUPABASE_DB_URL required for PgStore")
        # A connection POOL, not one shared connection: every request/poll borrows
        # its own connection, so concurrent threadpool requests and the auto-poller
        # never interleave statements on a single session. Staleness is handled by
        # proactive recycling — max_idle retires idle connections and max_lifetime
        # caps age — rather than a per-checkout SELECT 1 (that round-trip doubled
        # feed latency on the 3s poll, and a rare stale hit self-heals: the pool
        # discards a broken connection on error and the dashboard retries next tick).
        # prepare_threshold=None keeps us compatible with Supabase's pooler.
        self.pool = ConnectionPool(
            self._dsn, min_size=1, max_size=max(1, s.db_pool_max_size), open=False,
            max_idle=120, max_lifetime=1800,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
        )
        self.pool.open(wait=True, timeout=10)            # fail fast on a bad DSN/creds

    # --- borrow helpers (one connection per call, returned to the pool) -----
    def _one(self, sql: str, params=()):
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params=()):
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def _exec(self, sql: str, params=()) -> None:
        with self.pool.connection() as conn:
            conn.execute(sql, params)

    def _jsonb(self, value):
        from psycopg.types.json import Jsonb
        return Jsonb(value)

    # --- queries -----------------------------------------------------------
    def exists_by_hash(self, file_hash: str) -> Optional[str]:
        row = self._one("SELECT id FROM invoices WHERE file_hash = %s", (file_hash,))
        return str(row["id"]) if row else None

    def get_invoice(self, invoice_id: str) -> Optional[dict]:
        if not _is_uuid(invoice_id):
            return None
        # One borrowed connection for the whole multi-statement read.
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,)).fetchone()
            if not row:
                return None
            inv = dict(row)
            inv["id"] = str(inv["id"])
            inv["line_items"] = [dict(r) for r in conn.execute(
                "SELECT description, quantity, unit_price, amount FROM line_items WHERE invoice_id = %s ORDER BY id",
                (invoice_id,)).fetchall()]
            inv["tax_lines"] = [dict(r) for r in conn.execute(
                "SELECT label, rate, amount FROM tax_lines WHERE invoice_id = %s ORDER BY id",
                (invoice_id,)).fetchall()]
            inv["events"] = [dict(r) for r in conn.execute(
                "SELECT type, ts, detail FROM events WHERE invoice_id = %s ORDER BY seq",
                (invoice_id,)).fetchall()]
            vendor_id = inv.get("vendor_id")
            vrow = conn.execute("SELECT canonical_name FROM vendors WHERE id = %s",
                                (vendor_id,)).fetchone() if vendor_id else None
            inv["vendor_name"] = vrow["canonical_name"] if vrow else None
            inv["files"] = [dict(r) for r in conn.execute(
                "SELECT storage_path, mime, pages, original_name FROM invoice_files WHERE invoice_id = %s",
                (invoice_id,)).fetchall()]
        return inv

    def list_invoices(self, status: Optional[str] = None, date_from: Optional[str] = None,
                      date_to: Optional[str] = None) -> list[dict]:
        """Lean list (one query, vendor joined) — no per-row get_invoice. Optional
        date range filters on invoice_date (undated invoices excluded when set)."""
        sql = ("SELECT i.*, v.canonical_name AS vendor_name FROM invoices i "
               "LEFT JOIN vendors v ON v.id = i.vendor_id ")
        where, params = [], []
        if status:
            where.append("i.status = %s"); params.append(status)
        if date_from:
            where.append("i.invoice_date >= %s"); params.append(date_from)
        if date_to:
            where.append("i.invoice_date <= %s"); params.append(date_to)
        if where:
            sql += "WHERE " + " AND ".join(where) + " "
        sql += "ORDER BY i.created_at DESC"
        out = []
        for r in self._all(sql, tuple(params)):
            d = dict(r)
            d["id"] = str(d["id"])
            out.append(d)
        return out

    def delete_invoice(self, invoice_id: str) -> bool:
        """Strict delete: children cascade via FK; inbound self-references are
        cleared first so the delete can't FK-fail; originals removed best-effort."""
        if not _is_uuid(invoice_id):
            return False
        files = [r["storage_path"] for r in self._all(
            "SELECT storage_path FROM invoice_files WHERE invoice_id = %s", (invoice_id,))]
        with self.pool.connection() as conn:
            conn.execute("UPDATE invoices SET supersedes_id = NULL WHERE supersedes_id = %s", (invoice_id,))
            conn.execute("UPDATE invoices SET credit_of_id = NULL WHERE credit_of_id = %s", (invoice_id,))
            deleted = conn.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,)).rowcount > 0
        for p in files:
            try:
                self._delete_from_storage(p)
            except Exception:                            # cleanup is best-effort; the row is gone
                pass
        return deleted

    def _delete_from_storage(self, storage_path: Optional[str]) -> None:
        if not storage_path:
            return
        if os.path.isabs(storage_path) or storage_path.startswith("backend/local_storage"):
            if os.path.isfile(storage_path):            # local fallback original
                os.remove(storage_path)
            return
        s = get_settings()
        if not (s.supabase_url and s.supabase_service_key):
            return
        import httpx
        bucket, _, key = storage_path.partition("/")    # stored as "bucket/key"
        httpx.delete(f"{s.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{key}",
                     headers=self._storage_headers(), timeout=15)

    def activity_feed(self, limit: int = ACTIVITY_FEED_LIMIT) -> list[dict]:
        """Lean feed for the Activity view: bounded, no per-row fetch.

        The old path (list_invoices -> get_invoice per row) did 5 sub-queries
        per invoice — N+1 round-trips to Supabase on every poll. Here the most
        recent `limit` documents and only their events come back in two batched
        queries (on ONE borrowed connection) and are grouped in memory."""
        from backend.store import build_activity_rows

        with self.pool.connection() as conn:
            inv_rows = conn.execute(
                "SELECT i.id, i.invoice_number, i.doc_type, i.currency, i.total, "
                "i.base_total, i.base_currency, "
                "i.invoice_date, i.status, i.source, v.canonical_name AS vendor_name "
                "FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
                "ORDER BY i.created_at DESC LIMIT %s", (limit,)).fetchall()
            invoices, raw_ids = [], []
            for r in inv_rows:
                d = dict(r)
                raw_ids.append(d["id"])          # native UUID, to match the uuid column
                d["id"] = str(d["id"])
                invoices.append(d)
            events_by_invoice: dict[str, list[dict]] = {}
            if raw_ids:
                for r in conn.execute(
                        "SELECT invoice_id, type, ts, detail FROM events "
                        "WHERE invoice_id = ANY(%s) ORDER BY seq", (raw_ids,)).fetchall():
                    events_by_invoice.setdefault(str(r["invoice_id"]), []).append(
                        {"type": r["type"], "ts": r["ts"], "detail": r["detail"] or {}})
        return build_activity_rows(invoices, events_by_invoice, self.list_dead_letter())

    def count_invoices(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM invoices")["n"]

    def count_line_items(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM line_items")["n"]

    def list_vendors(self) -> list[dict]:
        rows = self._all("SELECT id, canonical_name, aliases, default_category FROM vendors")
        return [{"id": str(r["id"]), "canonical_name": r["canonical_name"],
                 "aliases": list(r["aliases"] or []), "default_category": r["default_category"]}
                for r in rows]

    def upsert_vendor(self, canonical_name: str, aliases=None, default_category=None) -> str:
        row = self._one(
            "INSERT INTO vendors (canonical_name, aliases, default_category) VALUES (%s, %s, %s) "
            "ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name "
            "RETURNING id", (canonical_name, aliases or [], default_category))
        return str(row["id"])

    def candidates_for_vendor(self, vendor_id: Optional[str]) -> list[dict]:
        if not vendor_id:
            return []
        rows = self._all(
            "SELECT id, doc_type, vendor_id, invoice_number, invoice_date, total, version, status, "
            "file_hash, (SELECT invoice_number FROM invoices x WHERE x.id = i.credit_of_id) "
            "  AS referenced_invoice_number "
            "FROM invoices i WHERE vendor_id = %s", (vendor_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["id"] = str(d["id"])
            # vendor_id MUST be a str: resolve compares it against the incoming
            # vendor_id (a str from upsert_vendor); a native UUID never matches,
            # silently breaking dedup/revision -> double-counting.
            if d.get("vendor_id") is not None:
                d["vendor_id"] = str(d["vendor_id"])
            out.append(d)
        return out

    def summary_rows(self, date_from: Optional[str] = None,
                     date_to: Optional[str] = None) -> list[dict]:
        sql = ("SELECT i.status, i.doc_type, i.base_total, i.category, i.is_invoice, "
               "v.canonical_name AS vendor FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id ")
        where, params = [], []
        if date_from:
            where.append("i.invoice_date >= %s"); params.append(date_from)
        if date_to:
            where.append("i.invoice_date <= %s"); params.append(date_to)
        if where:
            sql += "WHERE " + " AND ".join(where)
        return [dict(r) for r in self._all(sql, tuple(params))]

    def review_queue(self) -> list[dict]:
        rows = self._all(
            "SELECT id FROM invoices WHERE status IN ('needs_review','failed') ORDER BY created_at DESC")
        # Filter None: an invoice could be deleted between this SELECT and the
        # per-row fetch (non-atomic) — never return a None into the queue.
        return [inv for r in rows if (inv := self.get_invoice(str(r["id"]))) is not None]

    def review_counts(self) -> dict:
        nr = self._one(
            "SELECT COUNT(*) AS n FROM invoices WHERE status IN ('needs_review','failed')")["n"]
        dl = self._one("SELECT COUNT(*) AS n FROM dead_letter")["n"]
        return {"needs_review": nr, "dead_letter": dl, "total": nr + dl}

    # --- app settings (small key/value, e.g. digest on/off) ----------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._one("SELECT value FROM app_settings WHERE key = %s", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec(
            "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value))

    # --- mutations ---------------------------------------------------------
    def save_invoice(self, invoice: dict, line_items=None, tax_lines=None,
                     field_conf=None, events=None, mark_superseded=None) -> str:
        # Single statement = atomic (store_invoice commits invoice+children+events
        # together, R5), independent of the pool.
        row = self._one(
            "SELECT store_invoice(%s, %s, %s, %s, %s, %s) AS id",
            (self._jsonb(_payload(invoice)),
             self._jsonb([_payload(x) for x in (line_items or [])]),
             self._jsonb([_payload(x) for x in (tax_lines or [])]),
             self._jsonb([_payload(x) for x in (field_conf or [])]),
             self._jsonb(events or []),
             mark_superseded),
        )
        return str(row["id"])

    def append_event(self, invoice_id: str, type: str, detail: dict) -> None:
        self._exec(
            "INSERT INTO events (invoice_id, type, detail) VALUES (%s, %s, %s)",
            (invoice_id, type, self._jsonb(detail)))

    def update_status(self, invoice_id: str, status: str) -> None:
        self._exec(
            "UPDATE invoices SET status = %s, updated_at = now() WHERE id = %s", (status, invoice_id))

    def save_original(self, invoice_id: str, data: bytes, mime: str,
                      original_name: str, pages: Optional[int] = None) -> str:
        s = get_settings()
        storage_path = None
        if s.supabase_url and s.supabase_service_key:
            try:
                storage_path = self._upload_to_storage(invoice_id, data, mime, original_name)
            except Exception:                            # any storage failure -> keep locally, never lose the original
                storage_path = None
        if storage_path is None:                         # local fallback (dev / storage outage)
            folder = os.path.join("backend/local_storage", invoice_id)
            os.makedirs(folder, exist_ok=True)
            storage_path = os.path.join(folder, original_name or "original.bin")
            with open(storage_path, "wb") as f:
                f.write(data)
        # DB insert AFTER the (possibly slow) upload, so a pooled connection is
        # never held during network I/O.
        self._exec(
            "INSERT INTO invoice_files (invoice_id, storage_path, mime, pages, original_name) "
            "VALUES (%s, %s, %s, %s, %s)",
            (invoice_id, storage_path, mime, pages, original_name))
        return storage_path

    def _storage_headers(self) -> dict:
        # New-format Supabase keys (sb_secret_*) require BOTH apikey and Bearer;
        # the SDK at our pinned version mishandles them, so we call the REST API.
        k = get_settings().supabase_service_key
        return {"Authorization": f"Bearer {k}", "apikey": k}

    def _upload_to_storage(self, invoice_id: str, data: bytes, mime: str, original_name: str) -> str:
        import httpx

        s = get_settings()
        base = s.supabase_url.rstrip("/")
        bucket = s.supabase_storage_bucket
        self._ensure_bucket(base, bucket)
        key = f"{invoice_id}/{original_name or 'original.bin'}"
        resp = httpx.post(
            f"{base}/storage/v1/object/{bucket}/{key}",
            headers={**self._storage_headers(),
                     "Content-Type": mime or "application/octet-stream", "x-upsert": "true"},
            content=data, timeout=30,
        )
        resp.raise_for_status()
        return f"{bucket}/{key}"

    def _ensure_bucket(self, base: str, bucket: str) -> None:
        if getattr(self, "_bucket_ready", False):
            return
        import httpx
        # idempotent: 200 created or 409 already-exists are both fine
        httpx.post(f"{base}/storage/v1/bucket",
                   headers={**self._storage_headers(), "Content-Type": "application/json"},
                   json={"id": bucket, "name": bucket, "public": False}, timeout=15)
        self._bucket_ready = True

    # --- dead letter / runs ------------------------------------------------
    def add_dead_letter(self, source_ref, file_hash, error, tries, payload_path) -> str:
        row = self._one(
            "INSERT INTO dead_letter (source_ref, file_hash, error, tries, last_try, payload_path) "
            "VALUES (%s, %s, %s, %s, now(), %s) RETURNING id",
            (source_ref, file_hash, error, tries, payload_path))
        return str(row["id"])

    def list_dead_letter(self) -> list[dict]:
        return [dict(r) for r in self._all(
            "SELECT * FROM dead_letter ORDER BY last_try DESC")]

    def get_dead_letter(self, dl_id: str) -> Optional[dict]:
        if not _is_uuid(dl_id):
            return None
        r = self._one("SELECT * FROM dead_letter WHERE id = %s", (dl_id,))
        return dict(r) if r else None

    def delete_dead_letter(self, dl_id: str) -> None:
        self._exec("DELETE FROM dead_letter WHERE id = %s", (dl_id,))

    def is_email_processed(self, message_id: str) -> bool:
        if not message_id:
            return False
        return self._one(
            "SELECT 1 FROM processed_emails WHERE message_id = %s", (message_id,)) is not None

    def mark_email_processed(self, message_id: str) -> None:
        if not message_id:
            return
        self._exec(
            "INSERT INTO processed_emails (message_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (message_id,))

    def start_run(self, source: str) -> str:
        row = self._one(
            "INSERT INTO processing_runs (source) VALUES (%s) RETURNING id", (source,))
        return str(row["id"])

    def finish_run(self, run_id: str, processed: int, skipped: int, failed: int) -> None:
        self._exec(
            "UPDATE processing_runs SET finished_at = now(), processed = %s, skipped = %s, failed = %s "
            "WHERE id = %s", (processed, skipped, failed, run_id))

    def list_runs(self) -> list[dict]:
        return [dict(r) for r in self._all(
            "SELECT * FROM processing_runs ORDER BY started_at DESC")]

    def close(self) -> None:
        self.pool.close()
