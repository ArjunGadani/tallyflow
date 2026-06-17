"""FastAPI app + endpoints (§11).

/healthz is a pure 200 (Cloud Run probe / dashboard cold-start poll). Everything
heavy is lazy and behind Depends() so tests can inject a stub store + fake LLM.
Errors return graceful JSON — never a stack trace to the user (§0).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.config import get_settings
from backend.jsonutil import jsonify as _jsonify  # shared Decimal->str/date->ISO serializer
from backend.llm import LLM, LLMError, get_llm
from backend.store import Store, get_store
from backend.summary import reconcile_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tallyflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optional local auto-poller: ingest new email every poll_interval_sec while
    the server runs (so the inbox feels real-time without manual triggering).
    Ingest only — digests stay on the scheduled cron, so no digest spam."""
    s = get_settings()
    task = None
    if s.auto_poll and s.imap_user and s.imap_password:
        async def _loop():
            from backend.ingest_email import poll_and_process
            await asyncio.sleep(3)  # let startup settle, then poll promptly
            while True:
                try:
                    counts = await run_in_threadpool(poll_and_process, get_store(), get_llm())
                    if any(counts.values()):
                        logger.info("auto-poll: %s", counts)
                except Exception:
                    logger.exception("auto-poll cycle failed")  # never kill the loop
                await asyncio.sleep(s.poll_interval_sec)
        task = asyncio.create_task(_loop())
        logger.info("auto-poll enabled: every %ss", s.poll_interval_sec)
    yield
    if task:
        task.cancel()


app = FastAPI(title="TallyFlow", version="0.1.0", lifespan=lifespan)
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.cors_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- dependency seams (overridable in tests) --------------------------------
def store_dep() -> Store:
    return get_store()


def llm_dep() -> LLM:
    return get_llm()


def _health() -> dict:
    return {"status": "ok", "service": "tallyflow", "version": app.version}


# Two paths: Google Front End silently 404s a bare "/healthz" at the edge (never
# reaches the container), so the dashboard's boot poll uses "/api/healthz", which
# GFE always forwards. "/healthz" is kept for direct container / local probes.
@app.get("/healthz")
def healthz() -> dict:
    return _health()


@app.get("/api/healthz")
def api_healthz() -> dict:
    return _health()


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...), source: str = Form("upload"),
                 store: Store = Depends(store_dep), llm: LLM = Depends(llm_dep)):
    """Upload -> split (multi-invoice) -> resilient pipeline -> invoice + flow (§11).

    run_file never raises: a corrupt/unsupported file or LLM outage is dead-lettered
    and returned as a graceful 'failed' result, never a stack trace (§0, §2.10)."""
    from backend.retry import run_file

    data = await file.read()
    try:
        results = run_file(data, file.filename, file.content_type,
                           source=source, source_ref=file.filename, llm=llm, store=store)
    except Exception:                                 # defensive; run_file shouldn't raise
        logger.exception("ingest failed")
        return JSONResponse(status_code=500, content={
            "status": "failed", "branch": "error", "message": "processing failed"})

    primary = results[0]
    invoice = store.get_invoice(primary.invoice_id) if primary.invoice_id else None
    message = primary.message
    if len(results) > 1:
        message = (message + " · " if message else "") + f"split into {len(results)} invoices"
    return _jsonify({
        "invoice": invoice, "flow": primary.events, "branch": primary.branch,
        "status": primary.status, "message": message,
        "documents": [{"invoice_id": r.invoice_id, "branch": r.branch, "status": r.status}
                      for r in results],
    })


@app.get("/api/invoices")
def list_invoices(status: Optional[str] = None, date_from: Optional[str] = None,
                  date_to: Optional[str] = None, store: Store = Depends(store_dep)):
    return _jsonify({"invoices": store.list_invoices(status=status, date_from=date_from, date_to=date_to)})


@app.get("/api/activity")
def activity(store: Store = Depends(store_dep)):
    """Lean, prebuilt feed for the Activity view — one call, fixed query count
    (no N+1, no unused line items / tax lines / files)."""
    return _jsonify({"items": store.activity_feed()})


@app.get("/api/invoice/{invoice_id}")
def get_invoice(invoice_id: str, store: Store = Depends(store_dep)):
    inv = store.get_invoice(invoice_id)
    if not inv:
        return JSONResponse(status_code=404, content={"message": "not found"})
    return _jsonify(inv)


@app.delete("/api/invoice/{invoice_id}")
def delete_invoice_endpoint(invoice_id: str, store: Store = Depends(store_dep)):
    """Strict delete — removes the invoice and ALL its links (line items, tax
    lines, events, files cascade; inbound supersede/credit refs cleared)."""
    if not store.delete_invoice(invoice_id):
        return JSONResponse(status_code=404, content={"message": "not found"})
    return {"status": "deleted", "id": invoice_id}


@app.get("/api/invoice/{invoice_id}/flow")
def get_flow(invoice_id: str, store: Store = Depends(store_dep)):
    inv = store.get_invoice(invoice_id)
    if not inv:
        return JSONResponse(status_code=404, content={"message": "not found"})
    return _jsonify({"flow": inv["events"]})


@app.get("/api/summary")
def summary(date_from: Optional[str] = None, date_to: Optional[str] = None,
            store: Store = Depends(store_dep)):
    s = reconcile_summary(store.summary_rows(date_from=date_from, date_to=date_to), _settings.base_currency)
    return _jsonify({
        "base_currency": s.base_currency, "total_spend": s.total_spend,
        "invoices_counted": s.invoices_counted, "credits_total": s.credits_total,
        "pending_review_excluded": s.pending_review_excluded,
        "needs_review_count": s.needs_review_count,
        "by_category": s.by_category, "by_vendor": s.by_vendor,
    })


@app.get("/api/review-queue")
def review_queue(store: Store = Depends(store_dep)):
    return _jsonify({
        "needs_review": store.review_queue(),
        "dead_letter": store.list_dead_letter(),
    })


@app.post("/api/invoice/{invoice_id}/review")
def review_action(invoice_id: str, action: str = Form(...), store: Store = Depends(store_dep)):
    """State transition only (Q2) — approve -> clean (counts), dismiss -> failed
    (excluded). NOT a field editor; extracted numbers are never changed."""
    inv = store.get_invoice(invoice_id)
    if not inv:
        return JSONResponse(status_code=404, content={"message": "not found"})
    new_status = {"approve": "clean", "dismiss": "failed"}.get(action)
    if not new_status:
        return JSONResponse(status_code=400, content={"message": "action must be approve|dismiss"})
    store.update_status(invoice_id, new_status)
    store.append_event(invoice_id, "review_decision", {"action": action, "status": new_status})
    return _jsonify(store.get_invoice(invoice_id))


@app.post("/api/dead-letter/{dl_id}/retry")
def retry_dead_letter_endpoint(dl_id: str, store: Store = Depends(store_dep),
                               llm: LLM = Depends(llm_dep)):
    """Replay a dead-lettered document from its stored payload (§30)."""
    from backend.retry import retry_dead_letter
    try:
        results = retry_dead_letter(dl_id, store=store, llm=llm)
    except LookupError:
        return JSONResponse(status_code=404, content={"message": "dead-letter entry not found"})
    except FileNotFoundError:
        return JSONResponse(status_code=410, content={"message": "stored payload missing; cannot retry"})
    except Exception:
        logger.exception("dead-letter retry failed")
        return JSONResponse(status_code=500, content={"message": "retry failed"})
    primary = results[0] if results else None
    return _jsonify({
        "branch": primary.branch if primary else None,
        "status": primary.status if primary else None,
        "message": primary.message if primary else "nothing to retry",
        "documents": [{"invoice_id": r.invoice_id, "branch": r.branch, "status": r.status}
                      for r in results],
    })


@app.post("/api/dead-letter/{dl_id}/dismiss")
def dismiss_dead_letter_endpoint(dl_id: str, store: Store = Depends(store_dep)):
    if not store.get_dead_letter(dl_id):
        return JSONResponse(status_code=404, content={"message": "dead-letter entry not found"})
    store.delete_dead_letter(dl_id)
    return {"status": "dismissed", "id": dl_id}


@app.get("/api/review-count")
def review_count(store: Store = Depends(store_dep)):
    """Lightweight counts for the live Review nav badge."""
    return store.review_counts()


@app.get("/api/settings")
def get_settings_api(store: Store = Depends(store_dep)):
    """Dashboard-toggleable app settings (currently just the digest)."""
    return {"digest_enabled": store.get_setting("digest_enabled", "true") != "false"}


@app.post("/api/settings")
def set_settings_api(digest_enabled: bool = Form(...), store: Store = Depends(store_dep)):
    store.set_setting("digest_enabled", "true" if digest_enabled else "false")
    return {"digest_enabled": digest_enabled}


@app.get("/api/runs")
def runs(store: Store = Depends(store_dep)):
    return _jsonify({"runs": store.list_runs()})


@app.post("/api/run")
def trigger_run(store: Store = Depends(store_dep), llm: LLM = Depends(llm_dep)):
    """Manual trigger for the scheduled poll + pipeline + digest (§11)."""
    from backend.run_cron import run_scheduled
    try:
        return _jsonify(run_scheduled(store, llm))
    except Exception:
        logger.exception("scheduled run failed")
        return JSONResponse(status_code=500, content={"status": "failed",
                            "message": "scheduled run failed"})


# --- TallyChat: read-only conversational assistant (§6, §7) -----------------
class ChatTurnIn(BaseModel):
    # Constrain role so a client can't inject a 'system'/'tool' turn into the
    # conversation (the real system prompt must be the only system message).
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    history: list[ChatTurnIn] = []


_MAX_MESSAGE_CHARS = 2000
_MAX_HISTORY_TURNS = 100  # hard ceiling on request-body size (server also token-trims)
# Best-effort in-process guards. NOTE: Cloud Run scales to zero and runs multiple
# instances, so these reset per instance — a real deploy needs a distributed
# limiter + the daily spend cap enforced in a shared store (§8.5). Kept here so
# the contract and the fail-closed behaviour exist from day one.
_rl_hits: dict = {}
_spend = {"day": None, "count": 0}


def _rate_limited(key: str, per_min: int) -> bool:
    """Sliding-window limiter keyed on the CLIENT (IP), not a client-supplied id,
    so it can't be bypassed by rotating conversation_id. Prunes empty keys so the
    map can't grow without bound."""
    now = time.time()
    hits = [t for t in _rl_hits.get(key, []) if now - t < 60]
    limited = len(hits) >= per_min
    if not limited:
        hits.append(now)
    if hits:
        _rl_hits[key] = hits
    else:
        _rl_hits.pop(key, None)
    # Drop other clients' now-stale windows so the dict tracks only active callers.
    for k in [k for k, v in _rl_hits.items() if k != key and (not v or now - v[-1] > 60)]:
        _rl_hits.pop(k, None)
    return limited


def _spend_day() -> str:
    today = date.today().isoformat()
    if _spend["day"] != today:
        _spend["day"], _spend["count"] = today, 0
    return today


def _spend_remaining(cap: int) -> bool:
    """True if there's daily budget left (read-only; the counter is incremented
    only after an LLM call actually succeeds, so failures/demo don't burn it)."""
    _spend_day()
    return _spend["count"] < cap


def _spend_record(calls: int = 1) -> None:
    _spend_day()
    _spend["count"] += max(1, calls)


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, request: Request,
                        store: Store = Depends(store_dep), llm: LLM = Depends(llm_dep)):
    from backend.chat import run_chat

    s = get_settings()
    msg = (req.message or "").strip()
    if not msg:
        return JSONResponse(status_code=400, content={"message": "message is required"})
    if len(msg) > _MAX_MESSAGE_CHARS:
        return JSONResponse(status_code=400, content={"message": "message too long"})

    conv_id = req.conversation_id or str(uuid.uuid4())
    client_key = (request.client.host if request.client else None) or "anon"
    if _rate_limited(client_key, s.chat_rate_limit_per_min):
        return JSONResponse(status_code=429, content={
            "conversation_id": conv_id, "answer": None,
            "message": "too many requests — slow down a moment"})
    if not s.chat_demo_mode and not _spend_remaining(s.chat_daily_spend_calls):
        return JSONResponse(status_code=503, content={
            "conversation_id": conv_id, "answer": None,
            "message": "the assistant is paused for today (daily limit reached)"})

    history = [{"role": m.role, "content": m.content} for m in req.history[-_MAX_HISTORY_TURNS:]]
    history.append({"role": "user", "content": msg})
    try:
        res = await run_in_threadpool(run_chat, history, store=store, llm=llm, settings=s)
        if not s.chat_demo_mode:
            _spend_record(res.llm_calls)  # count ACTUAL Groq calls, not just turns
    except LLMError:
        logger.exception("chat: LLM error")
        return JSONResponse(status_code=503, content={
            "conversation_id": conv_id, "answer": None,
            "message": "the assistant is temporarily unavailable"})
    except Exception:
        logger.exception("chat failed")
        return JSONResponse(status_code=500, content={
            "conversation_id": conv_id, "answer": None, "message": "chat failed"})

    return _jsonify({
        "conversation_id": conv_id, "answer": res.answer,
        "citations": res.citations, "tool_trace": res.tool_trace,
        "result": res.result, "resolved_range": res.resolved_range,
        "max_iterations_reached": res.max_iterations_reached,
        "grounding_ok": res.grounding_ok,
    })


# --- serve the built dashboard (single-deploy: API + SPA on ONE origin) ------
# When the Vite build is present (in the Cloud Run image), the backend also
# serves the dashboard, so there's no separate static host and no CORS. This
# catch-all is registered LAST, so every /api and /healthz route above matches
# first; only unmatched GET paths fall through to a real asset or the SPA shell.
_DASHBOARD_DIST = os.path.abspath(os.environ.get("DASHBOARD_DIST", "dashboard/dist"))
if os.path.isfile(os.path.join(_DASHBOARD_DIST, "index.html")):
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        target = os.path.abspath(os.path.join(_DASHBOARD_DIST, full_path))
        # path-traversal guard, then real asset if it exists, else the SPA shell
        if (full_path and target.startswith(_DASHBOARD_DIST + os.sep)
                and os.path.isfile(target)):
            return FileResponse(target)
        return FileResponse(os.path.join(_DASHBOARD_DIST, "index.html"))
    logger.info("serving dashboard from %s", _DASHBOARD_DIST)
