"""Storage layer.

`Store` is the interface the pipeline talks to. `LocalStore` is a SQLite stub
for dev (no creds needed) that mirrors the Postgres schema closely enough to
exercise the real logic — including the two guarantees everything depends on:
atomic save (R5) and exact-duplicate rejection by file_hash (idempotency).
`SupabaseStore` (Phase 5) will back the same interface via the store_invoice
RPC. Money is stored as TEXT(str(Decimal)) so it round-trips exactly — never
float.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from backend.config import get_settings

# Columns that carry exact money / decimal values (TEXT in SQLite, Decimal in py).
_MONEY_COLS = {
    "subtotal", "tax_total", "discount", "shipping", "total",
    "base_total", "fx_rate", "confidence_overall",
}
_DATE_COLS = {"invoice_date", "due_date", "fx_date"}

_INVOICE_COLS = [
    "id", "vendor_id", "invoice_number", "invoice_date", "due_date", "doc_type",
    "currency", "subtotal", "tax_total", "discount", "shipping", "total",
    "base_currency", "base_total", "fx_rate", "fx_date", "category", "status",
    "version", "supersedes_id", "credit_of_id", "file_hash", "source",
    "source_ref", "confidence_overall", "is_invoice", "created_at", "updated_at",
]


def _to_db(col: str, val: Any) -> Any:
    if val is None:
        return None
    if col in _MONEY_COLS:
        return str(val)            # Decimal -> exact text
    if col in _DATE_COLS:
        return val.isoformat() if isinstance(val, (date, datetime)) else str(val)
    if col == "is_invoice":
        return 1 if val else 0
    return val


def _from_db(col: str, val: Any) -> Any:
    if val is None:
        return None
    if col in _MONEY_COLS:
        return Decimal(str(val))
    if col in _DATE_COLS:
        return date.fromisoformat(val)
    if col == "is_invoice":
        return bool(val)
    return val


def _money_str(v: Any) -> Optional[str]:
    """Serialize a child-row money/decimal value (quantity/amount/rate/...) to
    exact text for SQLite, or None."""
    return None if v is None else str(v)


def _new_id() -> str:
    return uuid.uuid4().hex


# Most recent N documents shown in the Activity feed. Bounds the per-poll query
# and payload so they don't grow with full history (the feed is a live tail).
ACTIVITY_FEED_LIMIT = 200
_DOC_TYPE_BRANCH = {"non_invoice": "non_invoice", "credit_note": "credit_note"}
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sort_dt(v: Any) -> datetime:
    """A uniformly comparable, tz-aware datetime for feed ordering. Absorbs the
    mix of ISO strings (SQLite), native datetimes/dates (Postgres) and missing
    values so sorting never raises on naive-vs-aware or compares raw strings."""
    dt = _parse_ts(v)
    if dt is None:
        return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _duration_ms(start: Optional[dict], end: Optional[dict]) -> Optional[int]:
    """Processing wall-clock: received -> stored, in ms. Anchored on the 'stored'
    event (not the last event) so actions appended later — a duplicate reprocess
    or a review decision hours afterward — can't inflate the time."""
    if not start or not end:
        return None
    a, b = _parse_ts(start.get("ts")), _parse_ts(end.get("ts"))
    if a is None or b is None:
        return None
    try:
        ms = int((b - a).total_seconds() * 1000)
    except TypeError:                       # one naive, one aware -> skip the badge
        return None
    return ms if ms >= 0 else None


def build_activity_rows(invoices: list[dict], events_by_invoice: dict[str, list[dict]],
                        dead_letter: list[dict]) -> list[dict]:
    """Build the Activity feed deterministically from already-fetched rows.

    Shared by both stores so the derivation (branch / arrival / duration / last
    step) lives in ONE place. Each invoice row carries only what the Activity
    view renders — never line items, tax lines or files (the N+1 that the
    per-row get_invoice would otherwise incur)."""
    rows: list[dict] = []
    for inv in invoices:
        evs = events_by_invoice.get(inv["id"], [])
        received = next((e for e in evs if e["type"] == "received"), None)
        resolved = next((e for e in evs if e["type"] == "resolved"), None)
        stored = next((e for e in evs if e["type"] == "stored"), None)
        last = evs[-1] if evs else None
        arrival = ((received or {}).get("detail") or {}).get("email_date") \
            or (received or {}).get("ts") \
            or inv.get("invoice_date")
        branch = ((resolved or {}).get("detail") or {}).get("branch") \
            or _DOC_TYPE_BRANCH.get(inv.get("doc_type"), "new")
        rows.append({
            "invoice_id": inv["id"],
            "title": inv.get("vendor_name") or inv.get("invoice_number") or "Document",
            "branch": branch,
            "source": inv.get("source") or "upload",
            "status": inv.get("status"),
            "last_step": last["type"] if last else None,
            "arrival": arrival,
            "duration_ms": _duration_ms(received, stored),
            "ts": (last or {}).get("ts") or arrival,
            "total": inv.get("total"),
            "currency": inv.get("currency"),
            "base_total": inv.get("base_total"),
            "base_currency": inv.get("base_currency"),
            "error": None,
        })
    for dl in dead_letter:
        ref = str(dl.get("source_ref") or "")
        rows.append({
            "invoice_id": None,
            "title": str(dl.get("original_name") or dl.get("source_ref") or "failed document"),
            "branch": "dead_letter",
            "source": "email" if "@" in ref else "upload",
            "status": "failed",
            "last_step": None,
            "arrival": None,
            "duration_ms": None,
            "ts": dl.get("last_try") or "",
            "total": None,
            "currency": None,
            "base_total": None,
            "base_currency": None,
            "error": str(dl.get("error") or dl.get("reason") or dl.get("message") or ""),
        })
    rows.sort(key=lambda r: _sort_dt(r.get("ts")), reverse=True)
    return rows


class Store:
    """Interface implemented by LocalStore (dev) and SupabaseStore (prod)."""

    def exists_by_hash(self, file_hash: str) -> Optional[str]: ...
    def save_invoice(self, invoice: dict, line_items=None, tax_lines=None,
                     field_conf=None, events=None, mark_superseded=None) -> str: ...
    def get_invoice(self, invoice_id: str) -> Optional[dict]: ...
    def append_event(self, invoice_id: str, type: str, detail: dict) -> None: ...
    def activity_feed(self, limit: int = ACTIVITY_FEED_LIMIT) -> list[dict]: ...
    def delete_invoice(self, invoice_id: str) -> bool: ...
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]: ...
    def set_setting(self, key: str, value: str) -> None: ...


class LocalStore(Store):
    def __init__(self, path: str = "backend/.tallyflow_local.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self) -> None:
        c = self.conn
        with c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS vendors (
                    id TEXT PRIMARY KEY, canonical_name TEXT UNIQUE NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]', default_category TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY, vendor_id TEXT, invoice_number TEXT,
                    invoice_date TEXT, due_date TEXT,
                    doc_type TEXT NOT NULL DEFAULT 'invoice',
                    currency TEXT, subtotal TEXT, tax_total TEXT, discount TEXT,
                    shipping TEXT, total TEXT, base_currency TEXT, base_total TEXT,
                    fx_rate TEXT, fx_date TEXT, category TEXT,
                    status TEXT NOT NULL DEFAULT 'received', version INTEGER NOT NULL DEFAULT 1,
                    supersedes_id TEXT, credit_of_id TEXT, file_hash TEXT,
                    source TEXT, source_ref TEXT, confidence_overall TEXT,
                    is_invoice INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_file_hash
                    ON invoices(file_hash) WHERE file_hash IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_invoices_vendor_number
                    ON invoices(vendor_id, invoice_number);
                CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
                CREATE TABLE IF NOT EXISTS line_items (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                    description TEXT, quantity TEXT, unit_price TEXT, amount TEXT
                );
                CREATE TABLE IF NOT EXISTS tax_lines (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                    label TEXT, rate TEXT, amount TEXT
                );
                CREATE TABLE IF NOT EXISTS field_conf (
                    invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                    field TEXT NOT NULL, confidence TEXT,
                    PRIMARY KEY (invoice_id, field)
                );
                CREATE TABLE IF NOT EXISTS invoice_files (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
                    storage_path TEXT NOT NULL, mime TEXT, pages INTEGER, original_name TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
                    invoice_id TEXT REFERENCES invoices(id) ON DELETE CASCADE,
                    ts TEXT NOT NULL, type TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_invoice ON events(invoice_id, seq);
                CREATE TABLE IF NOT EXISTS processing_runs (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    source TEXT, processed INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS dead_letter (
                    id TEXT PRIMARY KEY, source_ref TEXT, file_hash TEXT, error TEXT,
                    tries INTEGER NOT NULL DEFAULT 0, last_try TEXT, payload_path TEXT
                );
                CREATE TABLE IF NOT EXISTS processed_emails (
                    message_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                """
            )

    # --- queries -----------------------------------------------------------
    def exists_by_hash(self, file_hash: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT id FROM invoices WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row["id"] if row else None

    def get_invoice(self, invoice_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if not row:
            return None
        inv = {k: _from_db(k, row[k]) for k in row.keys()}
        inv["line_items"] = self._children(
            "line_items", invoice_id, ("quantity", "unit_price", "amount")
        )
        inv["tax_lines"] = self._children("tax_lines", invoice_id, ("rate", "amount"))
        inv["events"] = self._events(invoice_id)
        inv["vendor_name"] = self._vendor_name(inv.get("vendor_id"))
        inv["files"] = [dict(r) for r in self.conn.execute(
            "SELECT storage_path, mime, pages, original_name FROM invoice_files WHERE invoice_id = ?",
            (invoice_id,)).fetchall()]
        return inv

    def _vendor_name(self, vendor_id) -> Optional[str]:
        if not vendor_id:
            return None
        r = self.conn.execute(
            "SELECT canonical_name FROM vendors WHERE id = ?", (vendor_id,)
        ).fetchone()
        return r["canonical_name"] if r else None

    def _children(self, table: str, invoice_id: str, money_fields: tuple) -> list[dict]:
        rows = self.conn.execute(
            f"SELECT * FROM {table} WHERE invoice_id = ? ORDER BY rowid", (invoice_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in money_fields:
                if d.get(f) is not None:
                    d[f] = Decimal(str(d[f]))
            out.append(d)
        return out

    def _events(self, invoice_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, ts, type, detail FROM events WHERE invoice_id = ? ORDER BY seq",
            (invoice_id,),
        ).fetchall()
        return [
            {"id": r["id"], "ts": r["ts"], "type": r["type"], "detail": json.loads(r["detail"])}
            for r in rows
        ]

    def count_invoices(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]

    def count_line_items(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM line_items").fetchone()["n"]

    def list_invoices(self, status: Optional[str] = None, date_from: Optional[str] = None,
                      date_to: Optional[str] = None) -> list[dict]:
        """Lean list (one query, vendor joined) — the list view needs only scalar
        fields, never line items/tax lines/events. Optional date range filters on
        invoice_date (undated invoices are excluded when a range is set)."""
        sql = ("SELECT i.*, v.canonical_name AS vendor_name FROM invoices i "
               "LEFT JOIN vendors v ON v.id = i.vendor_id ")
        where, params = [], []
        if status:
            where.append("i.status = ?"); params.append(status)
        if date_from:
            where.append("i.invoice_date >= ?"); params.append(date_from)
        if date_to:
            where.append("i.invoice_date <= ?"); params.append(date_to)
        if where:
            sql += "WHERE " + " AND ".join(where) + " "
        sql += "ORDER BY i.created_at DESC"
        return [{k: _from_db(k, r[k]) for k in r.keys()}
                for r in self.conn.execute(sql, params).fetchall()]

    def delete_invoice(self, invoice_id: str) -> bool:
        """Strict delete: children (line items/tax lines/events/files/field_conf)
        cascade via FK; inbound self-references (supersedes_id/credit_of_id) are
        cleared first so the delete can't FK-fail; stored originals are removed
        best-effort. Returns False if no such invoice."""
        files = [r["storage_path"] for r in self.conn.execute(
            "SELECT storage_path FROM invoice_files WHERE invoice_id = ?", (invoice_id,)).fetchall()]
        with self.conn:
            self.conn.execute("UPDATE invoices SET supersedes_id = NULL WHERE supersedes_id = ?", (invoice_id,))
            self.conn.execute("UPDATE invoices SET credit_of_id = NULL WHERE credit_of_id = ?", (invoice_id,))
            deleted = self.conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,)).rowcount > 0
        for p in files:                                  # best-effort original cleanup
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
        try:
            folder = os.path.join("backend/local_storage", invoice_id)
            if os.path.isdir(folder):
                shutil.rmtree(folder)
        except OSError:
            pass
        return deleted

    def activity_feed(self, limit: int = ACTIVITY_FEED_LIMIT) -> list[dict]:
        """Lean feed for the Activity view: bounded, no N+1 (§9). Fetches the most
        recent `limit` documents and only their events (not the whole table)."""
        inv_rows = self.conn.execute(
            "SELECT i.id, i.invoice_number, i.doc_type, i.currency, i.total, "
            "i.base_total, i.base_currency, "
            "i.invoice_date, i.status, i.source, v.canonical_name AS vendor_name "
            "FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
            "ORDER BY i.created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        invoices = []
        for r in inv_rows:
            d = dict(r)
            d["total"] = Decimal(str(d["total"])) if d["total"] is not None else None
            d["base_total"] = Decimal(str(d["base_total"])) if d["base_total"] is not None else None
            d["invoice_date"] = date.fromisoformat(d["invoice_date"]) if d["invoice_date"] else None
            invoices.append(d)
        events_by_invoice: dict[str, list[dict]] = {}
        ids = [d["id"] for d in invoices]
        if ids:
            ph = ",".join("?" * len(ids))
            for r in self.conn.execute(
                    f"SELECT invoice_id, type, ts, detail FROM events "
                    f"WHERE invoice_id IN ({ph}) ORDER BY seq", ids).fetchall():
                events_by_invoice.setdefault(r["invoice_id"], []).append(
                    {"type": r["type"], "ts": r["ts"], "detail": json.loads(r["detail"])})
        return build_activity_rows(invoices, events_by_invoice, self.list_dead_letter())

    # --- app settings (small key/value, e.g. digest on/off) ----------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # --- mutations (atomic) ------------------------------------------------
    def save_invoice(self, invoice: dict, line_items=None, tax_lines=None,
                     field_conf=None, events=None, mark_superseded=None) -> str:
        """Atomic: invoice + children + events + supersede-mark commit together
        or not at all (R5). `with self.conn` rolls back on any exception, so a
        duplicate file_hash leaves no orphan rows."""
        iid = invoice.get("id") or _new_id()
        now = datetime.now(timezone.utc).isoformat()
        record = {**invoice, "id": iid}
        record.setdefault("created_at", now)
        record["updated_at"] = now
        cols = [c for c in _INVOICE_COLS if c in record]
        values = [_to_db(c, record[c]) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        with self.conn:  # transaction boundary
            self.conn.execute(
                f"INSERT INTO invoices ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
            for li in line_items or []:
                self.conn.execute(
                    "INSERT INTO line_items (id, invoice_id, description, quantity, unit_price, amount)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (_new_id(), iid, li.get("description"),
                     _money_str(li.get("quantity")),
                     _money_str(li.get("unit_price")),
                     _money_str(li.get("amount"))),
                )
            for tx in tax_lines or []:
                self.conn.execute(
                    "INSERT INTO tax_lines (id, invoice_id, label, rate, amount) VALUES (?, ?, ?, ?, ?)",
                    (_new_id(), iid, tx.get("label"),
                     _money_str(tx.get("rate")), _money_str(tx.get("amount"))),
                )
            for fc in field_conf or []:
                self.conn.execute(
                    "INSERT INTO field_conf (invoice_id, field, confidence) VALUES (?, ?, ?)",
                    (iid, fc.get("field"), _money_str(fc.get("confidence"))),
                )
            for ev in events or []:
                self._insert_event(iid, ev.get("type"), ev.get("detail") or {}, ts=ev.get("ts"))
            if mark_superseded:
                self.conn.execute(
                    "UPDATE invoices SET status = 'superseded', updated_at = ? WHERE id = ?",
                    (now, mark_superseded),
                )
        return iid

    def append_event(self, invoice_id: str, type: str, detail: dict) -> None:
        with self.conn:
            self._insert_event(invoice_id, type, detail)

    def _insert_event(self, invoice_id: str, type: str, detail: dict,
                      ts: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT INTO events (id, invoice_id, ts, type, detail) VALUES (?, ?, ?, ?, ?)",
            (_new_id(), invoice_id, ts or datetime.now(timezone.utc).isoformat(),
             type, json.dumps(detail)),
        )

    # --- vendors -----------------------------------------------------------
    def list_vendors(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, canonical_name, aliases, default_category FROM vendors"
        ).fetchall()
        return [
            {"id": r["id"], "canonical_name": r["canonical_name"],
             "aliases": json.loads(r["aliases"] or "[]"),
             "default_category": r["default_category"]}
            for r in rows
        ]

    def upsert_vendor(self, canonical_name: str, aliases: Optional[list] = None,
                      default_category: Optional[str] = None) -> str:
        existing = self.conn.execute(
            "SELECT id FROM vendors WHERE canonical_name = ?", (canonical_name,)
        ).fetchone()
        if existing:
            return existing["id"]
        vid = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO vendors (id, canonical_name, aliases, default_category, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (vid, canonical_name, json.dumps(aliases or []), default_category,
                 datetime.now(timezone.utc).isoformat()),
            )
        return vid

    def candidates_for_vendor(self, vendor_id: Optional[str]) -> list[dict]:
        """Existing invoices for a vendor — the resolution engine's candidate set."""
        if not vendor_id:
            return []
        rows = self.conn.execute(
            "SELECT id, doc_type, vendor_id, invoice_number, invoice_date, total, "
            "version, status, file_hash, "
            "(SELECT invoice_number FROM invoices x WHERE x.id = invoices.credit_of_id) "
            "  AS referenced_invoice_number "
            "FROM invoices WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r["id"], "doc_type": r["doc_type"], "vendor_id": r["vendor_id"],
                "invoice_number": r["invoice_number"],
                "invoice_date": _from_db("invoice_date", r["invoice_date"]),
                "total": _from_db("total", r["total"]),
                "version": r["version"], "status": r["status"], "file_hash": r["file_hash"],
                "referenced_invoice_number": r["referenced_invoice_number"],
            })
        return out

    # --- original file retention (§13 audit) -------------------------------
    def save_original(self, invoice_id: str, data: bytes, mime: str,
                      original_name: str, pages: Optional[int] = None) -> str:
        import os
        root = "backend/local_storage"
        folder = os.path.join(root, invoice_id)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, original_name or "original.bin")
        with open(path, "wb") as f:
            f.write(data)
        with self.conn:
            self.conn.execute(
                "INSERT INTO invoice_files (id, invoice_id, storage_path, mime, pages, original_name)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (_new_id(), invoice_id, path, mime, pages, original_name),
            )
        return path

    def update_status(self, invoice_id: str, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now(timezone.utc).isoformat(), invoice_id),
            )

    # --- summary / review queue -------------------------------------------
    def summary_rows(self, date_from: Optional[str] = None,
                     date_to: Optional[str] = None) -> list[dict]:
        """Rows for reconcile_summary: status, doc_type, base_total, category,
        vendor canonical name, is_invoice. Optional date range filters on
        invoice_date so the overview/spend can be scoped to a period."""
        sql = ("SELECT i.status, i.doc_type, i.base_total, i.category, i.is_invoice, "
               "       v.canonical_name AS vendor "
               "FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id ")
        where, params = [], []
        if date_from:
            where.append("i.invoice_date >= ?"); params.append(date_from)
        if date_to:
            where.append("i.invoice_date <= ?"); params.append(date_to)
        if where:
            sql += "WHERE " + " AND ".join(where)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"status": r["status"], "doc_type": r["doc_type"],
             "base_total": _from_db("base_total", r["base_total"]),
             "category": r["category"], "is_invoice": bool(r["is_invoice"]),
             "vendor": r["vendor"]}
            for r in rows
        ]

    def review_queue(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id FROM invoices WHERE status IN ('needs_review','failed') "
            "ORDER BY created_at DESC"
        ).fetchall()
        # Filter None (invoice deleted between SELECT and per-row fetch).
        return [inv for r in rows if (inv := self.get_invoice(r["id"])) is not None]

    def review_counts(self) -> dict:
        """Cheap counts for the live nav badge (no per-row fetch)."""
        nr = self.conn.execute(
            "SELECT COUNT(*) AS n FROM invoices WHERE status IN ('needs_review','failed')"
        ).fetchone()["n"]
        dl = self.conn.execute("SELECT COUNT(*) AS n FROM dead_letter").fetchone()["n"]
        return {"needs_review": nr, "dead_letter": dl, "total": nr + dl}

    # --- dead letter (§8, Phase 6) ----------------------------------------
    def add_dead_letter(self, source_ref: Optional[str], file_hash: Optional[str],
                        error: str, tries: int, payload_path: Optional[str]) -> str:
        did = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO dead_letter (id, source_ref, file_hash, error, tries, last_try, payload_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (did, source_ref, file_hash, error, tries,
                 datetime.now(timezone.utc).isoformat(), payload_path),
            )
        return did

    def list_dead_letter(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM dead_letter ORDER BY last_try DESC").fetchall()
        return [dict(r) for r in rows]

    def get_dead_letter(self, dl_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM dead_letter WHERE id = ?", (dl_id,)).fetchone()
        return dict(r) if r else None

    # --- processed-email tracking (idempotent polling, not IMAP read flag) ---
    def is_email_processed(self, message_id: str) -> bool:
        if not message_id:
            return False
        return self.conn.execute(
            "SELECT 1 FROM processed_emails WHERE message_id = ?", (message_id,)
        ).fetchone() is not None

    def mark_email_processed(self, message_id: str) -> None:
        if not message_id:
            return
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO processed_emails (message_id, processed_at) VALUES (?, ?)",
                (message_id, datetime.now(timezone.utc).isoformat()),
            )

    def delete_dead_letter(self, dl_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM dead_letter WHERE id = ?", (dl_id,))

    # --- processing runs (§8, Phase 9) ------------------------------------
    def start_run(self, source: str) -> str:
        rid = _new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO processing_runs (id, started_at, source) VALUES (?, ?, ?)",
                (rid, datetime.now(timezone.utc).isoformat(), source),
            )
        return rid

    def finish_run(self, run_id: str, processed: int, skipped: int, failed: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE processing_runs SET finished_at = ?, processed = ?, skipped = ?, failed = ? "
                "WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), processed, skipped, failed, run_id),
            )

    def list_runs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM processing_runs ORDER BY started_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()


_pg_store_cache: dict[str, "Store"] = {}


def get_store() -> Store:
    """LocalStore (SQLite) for dev; PgStore (Supabase Postgres) for prod.

    Only PgStore is cached: it owns a Supabase connection POOL that is expensive
    to build and meant to be long-lived and shared (each request/poll borrows its
    own connection from it). Cached per DSN so a settings flip rebuilds it.
    LocalStore is a cheap local file and is built per call — sharing one sqlite
    connection across the request threadpool and the auto-poll thread would clash
    on transaction state."""
    s = get_settings()
    if not s.store_is_supabase:
        return LocalStore()
    cached = _pg_store_cache.get(s.supabase_db_url)
    if cached is None:
        from backend.store_pg import PgStore
        cached = PgStore()
        _pg_store_cache[s.supabase_db_url] = cached
    return cached
