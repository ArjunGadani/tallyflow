"""TallyChat tool registry (§7.2).

Every tool is READ-ONLY and wraps a deterministic function the dashboard already
trusts (reconcile_summary, store queries) — so a grounded number IS the
dashboard's number. The LLM never computes anything here: it picks a tool + args;
this code does the work and tags each result with a `source` for citations.

Dates the model supplies are VALIDATED (never trusted); relative periods go
through resolve_date_range (Python calendar math), never the model.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Callable, Optional

from backend.config import get_settings
from backend.daterange import PHRASES, resolve_date_range
from backend.llm import ToolSpec
from backend.normalize import normalize_vendor
from backend.summary import reconcile_summary

logger = logging.getLogger("tallyflow")

STATUS_ENUM = ["received", "processing", "extracted", "needs_review", "clean",
               "stored", "superseded", "credited", "failed"]

_LIST_FIELDS = ("id", "vendor_name", "invoice_number", "invoice_date", "total",
                "currency", "base_total", "status", "doc_type", "category")
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 50
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clamp(limit, default=_DEFAULT_LIMIT, cap=_MAX_LIMIT) -> int:
    try:
        n = int(limit) if limit is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(n, cap))


def _valid_date(v) -> bool:
    if v is None:
        return True
    if not isinstance(v, str) or not _ISO.match(v):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def _date_error(df, dt) -> Optional[dict]:
    """Validate a date range. Returns an error dict (caller adds `source`) or None.
    Rejects malformed dates AND an inverted range (df > dt), which would otherwise
    silently return an empty result presented as an authoritative zero."""
    if not _valid_date(df) or not _valid_date(dt):
        return {"error": "bad_date", "hint": "use ISO YYYY-MM-DD or call resolve_date_range"}
    if df and dt and df > dt:
        return {"error": "bad_range", "hint": "date_from must be on or before date_to"}
    return None


# --- executors (store, args) -> dict (always carries a `source`) ------------
def _resolve_date_range(store, args) -> dict:
    phrase = args.get("phrase")
    try:
        out = resolve_date_range(phrase)
    except ValueError:
        return {"error": "bad_phrase", "allowed": list(PHRASES), "source": "daterange"}
    out["source"] = "daterange"
    return out


def _get_expense_summary(store, args) -> dict:
    df, dt = args.get("date_from"), args.get("date_to")
    err = _date_error(df, dt)
    if err:
        return {**err, "source": "summary"}
    base = get_settings().base_currency
    s = reconcile_summary(store.summary_rows(date_from=df, date_to=dt), base)
    return {
        "base_currency": s.base_currency, "total_spend": s.total_spend,
        "invoices_counted": s.invoices_counted, "credits_total": s.credits_total,
        "pending_review_excluded": s.pending_review_excluded,
        "needs_review_count": s.needs_review_count,
        "by_category": s.by_category, "by_vendor": s.by_vendor,
        "date_from": df, "date_to": dt, "source": "summary",
    }


def _list_invoices(store, args) -> dict:
    status = args.get("status")
    if status is not None and status not in STATUS_ENUM:
        return {"error": "bad_status", "allowed": STATUS_ENUM, "source": "list_invoices"}
    df, dt = args.get("date_from"), args.get("date_to")
    err = _date_error(df, dt)
    if err:
        return {**err, "source": "list_invoices"}
    limit = _clamp(args.get("limit"))
    rows = store.list_invoices(status=status, date_from=df, date_to=dt)
    out = [{k: r.get(k) for k in _LIST_FIELDS} for r in rows[:limit]]
    return {"invoices": out, "count": len(out), "truncated": len(rows) > limit,
            "source": "list_invoices"}


def _get_invoice(store, args) -> dict:
    iid = args.get("invoice_id")
    inv = store.get_invoice(iid) if iid else None
    if not inv:
        return {"error": "not_found", "invoice_id": iid, "source": f"invoice:{iid}"}
    inv = dict(inv)
    inv.pop("files", None)  # never expose storage paths to the model
    inv["source"] = f"invoice:{iid}"
    return inv


def _search_invoices_by_vendor(store, args) -> dict:
    query = (args.get("vendor_query") or "").strip()
    if not query:
        return {"error": "empty_query", "source": "vendor"}
    vendors = store.list_vendors()
    match = normalize_vendor(query, vendors)  # deterministic rapidfuzz, NOT LLM
    if match.is_new or not match.vendor_id:
        names = [v["canonical_name"] for v in vendors][:8]
        return {"matched": False, "query": query, "known_vendors": names, "source": "vendor"}
    limit = _clamp(args.get("limit"))
    cands = store.candidates_for_vendor(match.vendor_id)
    invs = [{k: r.get(k) for k in ("id", "invoice_number", "invoice_date", "total",
                                   "status", "doc_type")} for r in cands[:limit]]
    return {"matched": True, "vendor": {"id": match.vendor_id, "canonical_name": match.canonical_name,
                                        "score": round(match.score, 1)},
            "invoices": invs, "count": len(invs), "truncated": len(cands) > limit,
            "source": f"vendor:{match.vendor_id}"}


def _get_review_queue(store, args) -> dict:
    nr = store.review_queue()
    lean = [{k: r.get(k) for k in ("id", "vendor_name", "invoice_number", "total",
                                   "currency", "status", "confidence_overall")} for r in nr]
    dl = [{k: r.get(k) for k in ("id", "source_ref", "error")} for r in store.list_dead_letter()]
    return {"needs_review": lean, "needs_review_count": len(lean),
            "dead_letter": dl, "source": "review_queue"}


def _get_review_counts(store, args) -> dict:
    out = dict(store.review_counts())
    out["source"] = "review_counts"
    return out


def _list_vendors(store, args) -> dict:
    return {"vendors": store.list_vendors(), "source": "vendors"}


def _list_runs(store, args) -> dict:
    limit = _clamp(args.get("limit"), default=10, cap=20)
    return {"runs": store.list_runs()[:limit], "source": "runs"}


def _get_dead_letter(store, args) -> dict:
    dl = [{k: r.get(k) for k in ("id", "source_ref", "error", "tries", "last_try")}
          for r in store.list_dead_letter()]
    return {"dead_letter": dl, "count": len(dl), "source": "dead_letter"}


def _explain_invoice(store, args) -> dict:
    iid = args.get("invoice_id")
    inv = store.get_invoice(iid) if iid else None
    if not inv:
        return {"error": "not_found", "invoice_id": iid, "source": f"events:{iid}"}
    return {"invoice_id": iid, "status": inv.get("status"),
            "confidence_overall": inv.get("confidence_overall"),
            "events": inv.get("events", []), "source": f"events:{iid}"}


# --- registry ---------------------------------------------------------------
_DATE_PROPS = {
    "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD (optional)"},
    "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD (optional)"},
}

READ_ONLY_TOOLS: list[ToolSpec] = [
    ToolSpec("resolve_date_range",
             "Resolve a relative period (e.g. last_month) to concrete ISO dates. ALWAYS use "
             "this for any relative period; never invent dates yourself.",
             {"type": "object", "properties": {
                 "phrase": {"type": "string", "enum": list(PHRASES)}}, "required": ["phrase"]}),
    ToolSpec("get_expense_summary",
             "Reconciled expense summary (total_spend net of credits, by_category, by_vendor, "
             "pending_review_excluded). The authoritative spend figures.",
             {"type": "object", "properties": dict(_DATE_PROPS)}),
    ToolSpec("list_invoices", "List invoices (scalar fields only) with optional filters.",
             {"type": "object", "properties": {
                 "status": {"type": "string", "enum": STATUS_ENUM},
                 **_DATE_PROPS,
                 "limit": {"type": "integer", "description": "max 50"}}}),
    ToolSpec("get_invoice", "Full detail for one invoice by id (line items, tax, status, confidence).",
             {"type": "object", "properties": {"invoice_id": {"type": "string"}},
              "required": ["invoice_id"]}),
    ToolSpec("search_invoices_by_vendor",
             "Find invoices for a vendor by name (deterministic fuzzy match).",
             {"type": "object", "properties": {
                 "vendor_query": {"type": "string"},
                 "limit": {"type": "integer", "description": "max 50"}}, "required": ["vendor_query"]}),
    ToolSpec("get_review_queue", "Invoices needing review plus failed (dead-lettered) documents.",
             {"type": "object", "properties": {}}),
    ToolSpec("get_review_counts", "Counts of needs_review and dead_letter items.",
             {"type": "object", "properties": {}}),
    ToolSpec("list_vendors", "All known vendors with canonical names and default categories.",
             {"type": "object", "properties": {}}),
    ToolSpec("list_runs", "Recent processing-run history (processed/skipped/failed).",
             {"type": "object", "properties": {"limit": {"type": "integer", "description": "max 20"}}}),
    ToolSpec("get_dead_letter", "Documents that failed processing, with error reasons.",
             {"type": "object", "properties": {}}),
    ToolSpec("explain_invoice", "The audit-trail events for one invoice ('what happened to X').",
             {"type": "object", "properties": {"invoice_id": {"type": "string"}},
              "required": ["invoice_id"]}),
]

_EXECUTORS: dict[str, Callable] = {
    "resolve_date_range": _resolve_date_range,
    "get_expense_summary": _get_expense_summary,
    "list_invoices": _list_invoices,
    "get_invoice": _get_invoice,
    "search_invoices_by_vendor": _search_invoices_by_vendor,
    "get_review_queue": _get_review_queue,
    "get_review_counts": _get_review_counts,
    "list_vendors": _list_vendors,
    "list_runs": _list_runs,
    "get_dead_letter": _get_dead_letter,
    "explain_invoice": _explain_invoice,
}


def read_only_specs() -> list[ToolSpec]:
    return list(READ_ONLY_TOOLS)


def execute(name: str, args: dict, store) -> dict:
    """Dispatch a tool. Never raises into the loop — unknown tool / executor error
    returns a structured {error} dict (still tagged with a source)."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return {"error": "unknown_tool", "name": name, "source": name}
    try:
        return fn(store, args or {})
    except Exception:  # defensive: a tool bug must not crash the chat turn
        # Log the full traceback server-side; return a generic error to the model
        # (never leak raw exception text / SQL / paths into the LLM context).
        logger.exception("chat tool %s failed", name)
        return {"error": "tool_failed", "source": name}
