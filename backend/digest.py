"""Scheduled digest (§10): a run summary sent to Email (HTML) + Slack (blocks),
always consistent with stored data. Aggregation + rendering are pure; sending is
thin IO (Resend/SMTP, Slack webhook).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from backend.config import get_settings
from backend.store import Store
from backend.summary import reconcile_summary

logger = logging.getLogger("tallyflow.digest")


def _money(amount, currency: str) -> str:
    return f"{currency} {Decimal(amount or 0):,.2f}"


def build_digest_data(store: Store, run_counts: Optional[dict] = None) -> dict:
    settings = get_settings()
    s = reconcile_summary(store.summary_rows(), settings.base_currency)
    top_categories = sorted(s.by_category.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_vendors = sorted(s.by_vendor.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "base_currency": s.base_currency,
        "total_spend": s.total_spend,
        "invoices_counted": s.invoices_counted,
        "credits_total": s.credits_total,
        "pending_review_excluded": s.pending_review_excluded,
        "needs_review_count": s.needs_review_count,
        "dead_letter_count": len(store.list_dead_letter()),
        "top_categories": top_categories,
        "top_vendors": top_vendors,
        "run": run_counts or {},
        "dashboard_url": settings.dashboard_url,
    }


def render_email_html(d: dict) -> str:
    cur = d["base_currency"]
    cats = "".join(f"<li>{c}: {_money(a, cur)}</li>" for c, a in d["top_categories"]) or "<li>—</li>"
    vendors = "".join(f"<li>{v}: {_money(a, cur)}</li>" for v, a in d["top_vendors"]) or "<li>—</li>"
    run = d.get("run", {})
    return f"""<html><body style="font-family:sans-serif;color:#1f2933">
<h2 style="color:#7c5cff">TallyFlow — Processing Digest</h2>
<p style="font-size:22px"><b>Total spend (net of credits):</b> {_money(d['total_spend'], cur)}</p>
<ul>
  <li>Invoices counted: {d['invoices_counted']}</li>
  <li>Credits applied: {_money(d['credits_total'], cur)}</li>
  <li><b>Needs review:</b> {d['needs_review_count']} (excluded: {_money(d['pending_review_excluded'], cur)})</li>
  <li>Dead-letter (failed): {d['dead_letter_count']}</li>
  <li>This run — processed {run.get('processed', 0)}, skipped {run.get('skipped', 0)}, failed {run.get('failed', 0)}</li>
</ul>
<h3>Top categories</h3><ul>{cats}</ul>
<h3>Top vendors</h3><ul>{vendors}</ul>
<p><a href="{d['dashboard_url']}">Open dashboard →</a></p>
</body></html>"""


def render_slack_blocks(d: dict) -> list:
    cur = d["base_currency"]
    run = d.get("run", {})
    cats = "\n".join(f"• {c}: {_money(a, cur)}" for c, a in d["top_categories"]) or "—"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "TallyFlow — Processing Digest"}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f"*Total spend (net of credits):* {_money(d['total_spend'], cur)}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Invoices:* {d['invoices_counted']}"},
            {"type": "mrkdwn", "text": f"*Credits:* {_money(d['credits_total'], cur)}"},
            {"type": "mrkdwn", "text": f"*Needs review:* {d['needs_review_count']}"},
            {"type": "mrkdwn", "text": f"*Dead-letter:* {d['dead_letter_count']}"},
            {"type": "mrkdwn", "text": f"*Run:* {run.get('processed', 0)} ok / {run.get('failed', 0)} failed"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Top categories*\n{cats}"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open dashboard"},
             "url": d["dashboard_url"]}]},
    ]


# --- sending (live IO) ------------------------------------------------------
def send_digest(store: Store, run_counts: Optional[dict] = None) -> dict:
    data = build_digest_data(store, run_counts)
    sent = {"email": False, "slack": False}
    try:
        if _send_email(render_email_html(data)):
            sent["email"] = True
    except Exception as exc:
        logger.warning("digest email failed: %s", exc)
    try:
        if _send_slack(render_slack_blocks(data)):
            sent["slack"] = True
    except Exception as exc:
        logger.warning("digest slack failed: %s", exc)
    return sent


def _send_email(html: str, subject: str = "TallyFlow — Processing Digest") -> bool:
    s = get_settings()
    if s.resend_api_key and s.digest_to:
        import httpx
        httpx.post("https://api.resend.com/emails",
                   headers={"Authorization": f"Bearer {s.resend_api_key}"},
                   json={"from": s.digest_from, "to": [s.digest_to],
                         "subject": subject, "html": html}, timeout=20).raise_for_status()
        return True
    if s.smtp_user and s.smtp_pass and s.digest_to:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, s.digest_from, s.digest_to
        msg.set_content("HTML digest — open in an HTML-capable client.")
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(s.smtp_host, s.smtp_port) as server:
            server.starttls()
            server.login(s.smtp_user, s.smtp_pass)
            server.send_message(msg)
        return True
    return False


def _send_slack(blocks: list) -> bool:
    s = get_settings()
    if not s.slack_webhook:
        return False
    import httpx
    httpx.post(s.slack_webhook, json={"blocks": blocks}, timeout=20).raise_for_status()
    return True
