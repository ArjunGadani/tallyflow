"""Email ingestion (§1, scenarios 5-11).

Parsing is pure (testable): unwrap multipart + nested forwarded .eml, collect
attachments, fall back to the body when there's no attachment (body-only
invoice). A deterministic junk filter drops logos/signatures/tiny inline images
before any Groq call (R9). The IMAP poll itself is thin IO over UNSEEN messages
(marked seen after processing -> idempotent polling, on top of file-hash dedup).
"""
from __future__ import annotations

import email
import io
import logging
import time
from dataclasses import dataclass, field
from email import policy
from typing import Optional

from backend.classify import is_probably_junk, is_probably_promo_body
from backend.config import get_settings
from backend.retry import run_file
from backend.store import Store, get_store

logger = logging.getLogger("tallyflow.ingest")


@dataclass
class ParsedEmail:
    subject: Optional[str] = None
    from_addr: Optional[str] = None
    message_id: str = ""
    body_text: str = ""
    date: Optional[str] = None              # ISO arrival time (from the Date header)
    is_bulk: bool = False                   # RFC bulk-mail headers (List-Unsubscribe, …)
    attachments: list = field(default_factory=list)  # [{filename, mime, data}]


def _is_bulk_headers(msg) -> bool:
    """RFC-standard bulk / automated-mail signals — language-agnostic and far more
    robust than keyword matching. List-Unsubscribe / List-Id are set by virtually
    all compliant marketing & notification senders; Precedence: bulk|list|junk and
    Auto-Submitted mark automated blasts."""
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return True
    if (msg.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return True
    return (msg.get("Auto-Submitted") or "").strip().lower() not in ("", "no")


def parse_email(raw: bytes) -> ParsedEmail:
    from email.utils import parsedate_to_datetime

    msg = email.message_from_bytes(raw, policy=policy.default)
    raw_date = msg.get("Date")
    try:
        date_iso = parsedate_to_datetime(raw_date).isoformat() if raw_date else None
    except (TypeError, ValueError):
        date_iso = raw_date
    parsed = ParsedEmail(
        subject=msg.get("Subject"),
        from_addr=_addr(msg.get("From")),
        message_id=(msg.get("Message-ID") or "").strip(),
        date=date_iso,
        is_bulk=_is_bulk_headers(msg),
    )
    body: list[str] = []
    _walk(msg, body, parsed.attachments)
    parsed.body_text = "\n".join(body).strip()
    return parsed


def _addr(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    # "Name <a@b.com>" -> a@b.com
    if "<" in value and ">" in value:
        return value[value.index("<") + 1:value.index(">")].strip()
    return value.strip()


def _walk(part, body: list, attachments: list) -> None:
    ctype = part.get_content_type()
    disp = part.get_content_disposition()
    filename = part.get_filename()

    if ctype.startswith("multipart/"):
        for p in part.iter_parts():
            _walk(p, body, attachments)
        return

    if ctype == "message/rfc822":                 # nested / forwarded email
        payload = part.get_content()
        if isinstance(payload, (bytes, bytearray)):
            nested = email.message_from_bytes(bytes(payload), policy=policy.default)
        elif isinstance(payload, str):
            nested = email.message_from_string(payload, policy=policy.default)
        else:
            nested = payload
        _walk(nested, body, attachments)
        return

    if ctype == "text/plain" and not filename and disp != "attachment":
        try:
            body.append(part.get_content())
        except Exception:
            pass
        return

    if ctype == "text/html" and not filename and disp != "attachment":
        return                                    # ignore HTML alt body

    # otherwise: a file part (attachment or inline)
    try:
        payload = part.get_content()
        if isinstance(payload, str):
            data = payload.encode("utf-8", "ignore")
        elif isinstance(payload, (bytes, bytearray)):
            data = bytes(payload)
        else:
            data = part.get_payload(decode=True) or b""
    except Exception:
        data = part.get_payload(decode=True) or b""
    attachments.append({"filename": filename or ctype.replace("/", "."),
                        "mime": ctype, "data": bytes(data)})


def _image_dims(data: bytes) -> tuple[Optional[int], Optional[int]]:
    try:
        from PIL import Image
        return Image.open(io.BytesIO(data)).size
    except Exception:
        return (None, None)


def extract_documents(parsed: ParsedEmail) -> list[dict]:
    """Documents worth processing: non-junk attachments, or the body if there are
    none (body-only invoice, scenario 7)."""
    docs: list[dict] = []
    for att in parsed.attachments:
        w = h = None
        if (att["mime"] or "").startswith("image/"):
            w, h = _image_dims(att["data"])
        if is_probably_junk(att["filename"], att["mime"], w, h):
            continue
        docs.append({"filename": att["filename"], "mime": att["mime"],
                     "data": att["data"],
                     "source_ref": f"{parsed.message_id}:{att['filename']}"})
    # Body-only invoice (scenario 7): only when there were NO attachments at all.
    # If attachments existed but were all junk, the body is just cover text.
    if not parsed.attachments and parsed.body_text.strip():
        if is_probably_promo_body(parsed.subject, parsed.body_text, bulk=parsed.is_bulk):
            # Promo / newsletter / bulk / no-invoice body: drop before the LLM (R9)
            # — no Groq call, no stored row. The email is still marked processed by
            # the caller, so it won't be re-polled.
            logger.info("skipped promo/non-invoice body-only email: %r", parsed.subject)
            return docs
        docs.append({"filename": "email_body.txt", "mime": "text/plain",
                     "data": parsed.body_text.encode("utf-8"),
                     "source_ref": f"{parsed.message_id}:body"})
    return docs


def process_email_bytes(raw: bytes, store: Store, llm, *, sleep=time.sleep) -> dict:
    """Parse one email and run each document through the resilient pipeline."""
    parsed = parse_email(raw)
    meta = {"email_date": parsed.date, "email_from": parsed.from_addr,
            "email_subject": parsed.subject}
    counts = {"processed": 0, "skipped": 0, "failed": 0}
    for d in extract_documents(parsed):
        # run_file splits multi-invoice attachments and processes each resiliently.
        for res in run_file(d["data"], d["filename"], d["mime"], source="email",
                            source_ref=d["source_ref"], store=store, llm=llm, sleep=sleep,
                            metadata=meta):
            if res.branch == "dead_letter" or res.status == "failed":
                counts["failed"] += 1
            elif res.branch in ("exact_duplicate", "logical_duplicate", "non_invoice"):
                counts["skipped"] += 1
            else:
                counts["processed"] += 1
    return counts


# --- IMAP IO (live; not unit-tested) ---------------------------------------
def _message_id_from_header(fetched) -> str:
    try:
        hdr = email.message_from_bytes(fetched[0][1], policy=policy.default)
        return (hdr.get("Message-ID") or "").strip()
    except Exception:
        return ""


def poll_and_process(store: Optional[Store] = None, llm=None, max_messages: int = 50) -> dict:
    """Poll the inbox and process any message we haven't seen BY MESSAGE-ID
    (independent of the IMAP read flag — opening mail in a client doesn't cause a
    skip or a reprocess). Uses BODY.PEEK so the read state is never altered;
    file-hash + message-id give idempotent replay."""
    import hashlib
    import imaplib

    store = store or get_store()
    s = get_settings()
    totals = {"processed": 0, "skipped": 0, "failed": 0}
    if not (s.imap_host and s.imap_user and s.imap_password):
        return totals

    conn = imaplib.IMAP4_SSL(s.imap_host)
    try:
        conn.login(s.imap_user, s.imap_password)
        conn.select(s.imap_folder, readonly=True)  # readonly: never touch the read flag
        _typ, data = conn.search(None, "ALL")
        ids = data[0].split()[-max_messages:]  # most recent N
        for num in ids:
            # cheap header peek first — skip already-processed without downloading the body
            _t, hd = conn.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            mid = _message_id_from_header(hd)
            if mid and store.is_email_processed(mid):
                totals["skipped"] += 1            # already seen -> count it so a run isn't a bare 0/0/0
                continue
            _t2, md = conn.fetch(num, "(BODY.PEEK[])")
            raw = md[0][1]
            if not mid:  # no Message-ID header -> fall back to a content hash
                mid = parse_email(raw).message_id or "sha:" + hashlib.sha256(raw).hexdigest()
                if store.is_email_processed(mid):
                    totals["skipped"] += 1
                    continue
            counts = process_email_bytes(raw, store, llm)
            store.mark_email_processed(mid)
            for k in totals:
                totals[k] += counts[k]
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return totals
