#!/usr/bin/env python3
"""
סוכן מענה אישי — Batch Processor

שולף מיילים מתווית VIP ב-Gmail, מייצר תגובות אישיות
דרך Claude Batch API (עם prompt caching), ויוצר טיוטות reply.

שימוש:
    python run_reply_agent.py                # הרצה מלאה (שליפה מחדש של כל VIP)
    python run_reply_agent.py --resume       # המשך מ-batch קיים
    python run_reply_agent.py --drafts-only  # רק יצירת טיוטות מתוצאות קיימות
    python run_reply_agent.py --dry-run      # הכל חוץ מיצירת טיוטות
    python run_reply_agent.py --limit 5      # רק 5 מיילים ראשונים (לבדיקה)
    python run_reply_agent.py --use-existing-emails  # השתמש ב-emails.json קיים
"""

import anthropic
import base64
import json
import os
import re
import sys
import time
from argparse import ArgumentParser
from datetime import datetime
from email.mime.text import MIMEText
from html import escape, unescape
from pathlib import Path

import requests as http_requests
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent

load_dotenv(SCRIPT_DIR / ".env")

MODEL = "claude-opus-4-6"
MAX_TOKENS = 2048

# Pricing (per 1M tokens) — Claude Opus 4.6
PRICE_INPUT = 5.00
PRICE_OUTPUT = 25.00

# Notion — optional cost reporting
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "")

INSTRUCTIONS_FILE = SCRIPT_DIR.parent / "instructions.md"
GUIDES_FILE = SCRIPT_DIR.parent / "guides-catalog.md"

EMAILS_FILE = SCRIPT_DIR / "emails.json"
RESULTS_FILE = SCRIPT_DIR / "results.json"
DRAFTS_FILE = SCRIPT_DIR / "drafts_report.json"
STATE_FILE = SCRIPT_DIR / "state.json"

FROM_EMAIL = os.environ.get("FROM_EMAIL", "you@example.com")
WA_PROGRAM_URL = os.environ.get("WA_PROGRAM_URL", "https://wa.me/YOUR_NUMBER")


# ─── Gmail Helpers ────────────────────────────────────────────


def get_gmail_token():
    """Get a fresh access token using the refresh token."""
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        if var not in os.environ:
            sys.exit(f"❌ חסר משתנה סביבה: {var}")

    resp = http_requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.environ["GMAIL_CLIENT_ID"],
            "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
            "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def gmail_get(endpoint, token, params=None):
    resp = http_requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    resp.raise_for_status()
    return resp.json()


def gmail_post(endpoint, token, body):
    resp = http_requests.post(
        f"https://gmail.googleapis.com/gmail/v1/users/me/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    resp.raise_for_status()
    return resp.json()


def strip_html(html_text):
    """Basic HTML to plain text."""
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I)
    text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_body(payload):
    """Recursively extract text from Gmail MIME payload."""
    plain_parts = []
    html_parts = []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if mime == "text/plain" and data:
            plain_parts.append(
                base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            )
        elif mime == "text/html" and data:
            html_parts.append(
                base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            )
        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)

    plain = "\n".join(plain_parts).strip()
    if plain:
        return plain
    html = "\n".join(html_parts).strip()
    if html:
        return strip_html(html)
    return ""


def fetch_vip_emails(token, limit=None):
    """Fetch all emails from the VIP label."""
    all_emails = []
    page_token = None

    while True:
        params = {"q": "label:VIP", "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token

        data = gmail_get("messages", token, params)

        for ref in data.get("messages", []):
            if limit and len(all_emails) >= limit:
                return all_emails

            msg = gmail_get(
                f"messages/{ref['id']}", token, {"format": "full"}
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in msg["payload"]["headers"]
            }
            body = extract_body(msg["payload"])

            all_emails.append(
                {
                    "id": msg["id"],
                    "threadId": msg["threadId"],
                    "messageId": headers.get("message-id", ""),
                    "from": headers.get("from", ""),
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "internalDate": msg.get("internalDate", ""),
                    "body": body,
                }
            )
            print(
                f"  📧 {len(all_emails)}: "
                f"{headers.get('from', '?')[:45]} — "
                f"{headers.get('subject', '')[:40]}"
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return all_emails


def create_reply_draft(token, email_data, reply_text):
    """Create a threaded reply draft in Gmail."""
    safe_body = escape(reply_text).replace("\n", "<br>")
    footer_html = (
        "<br><br>"
        "<div dir='rtl'>"
        "💡 המייל הזה נכתב על ידי סוכן AI שבניתי.<br>"
        "רוצה ללמוד לבנות דברים כאלה שעובדים לבד?<br>"
        "אפשר לבדוק התאמה ל״טירונות סוכנים״ "
        f"<a href='{WA_PROGRAM_URL}'>בקישור</a>"
        "</div>"
    )
    html_body = f"<div dir='rtl'>{safe_body}</div>{footer_html}"
    msg = MIMEText(html_body, "html", "utf-8")
    # Extract only the email address, strip Hebrew/special display names
    from_raw = email_data["from"]
    addr_match = re.search(r'<([^>]+)>', from_raw)
    to_addr = addr_match.group(1) if addr_match else from_raw
    msg["To"] = to_addr
    msg["From"] = FROM_EMAIL

    subj = email_data["subject"]
    msg["Subject"] = (
        subj if subj.lower().startswith("re:") else f"Re: {subj}"
    )

    if email_data["messageId"]:
        msg["In-Reply-To"] = email_data["messageId"]
        msg["References"] = email_data["messageId"]

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return gmail_post(
        "drafts",
        token,
        {"message": {"threadId": email_data["threadId"], "raw": raw}},
    )


# ─── Claude Batch API ────────────────────────────────────────


def get_label_id(token, label_name):
    """Get Gmail label ID by name."""
    resp = http_requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    for label in resp.json().get("labels", []):
        if label["name"] == label_name:
            return label["id"]
    return None


def modify_thread_labels(token, thread_id, add_labels=None, remove_labels=None):
    """Add/remove labels from a Gmail thread."""
    body = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    resp = http_requests.post(
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}/modify",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    resp.raise_for_status()


def group_by_thread(emails):
    """Group emails by threadId, sorted oldest-first within each thread."""
    threads = {}
    for email in emails:
        tid = email["threadId"]
        threads.setdefault(tid, []).append(email)
    for tid in threads:
        threads[tid].sort(key=lambda e: int(e.get("internalDate", "0")))
    return threads


def build_batch(threads, instructions, guides):
    """Build batch request items with prompt caching — one item per thread."""
    items = []
    for tid, thread_emails in threads.items():
        if len(thread_emails) == 1:
            em = thread_emails[0]
            user_msg = (
                "מייל לעיבוד:\n\n"
                f"שולח: {em['from']}\n"
                f"כותרת: {em['subject']}\n"
                f"תאריך: {em['date']}\n"
                f"תוכן:\n{em['body']}\n\n"
            )
        else:
            parts = [
                f"שרשור עם {len(thread_emails)} הודעות — ענה תגובה אחת שמתייחסת לכולן:\n"
            ]
            for i, em in enumerate(thread_emails, 1):
                parts.append(
                    f"הודעה {i}:\n"
                    f"שולח: {em['from']}\n"
                    f"תאריך: {em['date']}\n"
                    f"תוכן:\n{em['body']}\n"
                )
            user_msg = "\n".join(parts) + "\n"

        user_msg += (
            "---\n\n"
            "עבד את המייל לפי ההוראות. "
            "החזר תשובה בפורמט JSON הבא **בלבד**, ללא טקסט נוסף:\n\n"
            '{"skip": false, "skip_reason": null, '
            '"category": "שם הקטגוריה", '
            '"reply_text": "טקסט התגובה המלא"}\n\n'
            "אם צריך לדלג (מייל אוטומטי, ריק, לא בעברית) — "
            "החזר skip=true עם הסיבה.\n"
            "אם דורש בדיקה מיוחדת — הוסף [לבדיקה] בתחילת reply_text."
        )

        items.append(
            {
                "custom_id": tid,
                "params": {
                    "model": MODEL,
                    "max_tokens": MAX_TOKENS,
                    "system": [
                        {
                            "type": "text",
                            "text": instructions,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": f"## קטלוג מדריכים\n\n{guides}",
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                    "messages": [{"role": "user", "content": user_msg}],
                },
            }
        )
    return items


def submit_batch(items):
    """Submit batch to Anthropic and poll until complete."""
    client = anthropic.Anthropic()

    print(f"\n📤 שולח batch ({len(items)} בקשות)...")
    batch = client.messages.batches.create(requests=items)
    print(f"   Batch ID: {batch.id}")

    STATE_FILE.write_text(
        json.dumps(
            {
                "batch_id": batch.id,
                "submitted": datetime.now().isoformat(),
                "count": len(items),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return poll_batch(client, batch.id)


def poll_batch(client, batch_id):
    """Poll a batch until it ends, then collect results and token usage."""
    interval = 10
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        c = batch.request_counts
        total = (
            c.processing + c.succeeded + c.errored + c.canceled + c.expired
        )
        print(
            f"   ⏳ {batch.processing_status} | "
            f"✅ {c.succeeded}/{total} | "
            f"❌ {c.errored} | "
            f"⏳ {c.processing} בעיבוד"
        )
        if batch.processing_status == "ended":
            break
        time.sleep(interval)
        interval = min(interval * 1.5, 120)

    results = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0

    for r in client.messages.batches.results(batch_id):
        if r.result.type == "succeeded":
            raw_text = r.result.message.content[0].text
            usage = r.result.message.usage
            total_input_tokens += getattr(usage, "input_tokens", 0)
            total_output_tokens += getattr(usage, "output_tokens", 0)
            total_cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0)
            total_cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0)
            results[r.custom_id] = _parse_json_response(raw_text)
        else:
            results[r.custom_id] = {
                "status": "error",
                "error": str(r.result.type),
            }

    # Prompt Caching pricing (Claude Opus 4.6):
    # cache_creation = $6.25/M (25% more than input)
    # cache_read    = $0.50/M  (90% cheaper than input)
    actual_cost = (
        total_input_tokens / 1_000_000 * PRICE_INPUT
        + total_cache_creation_tokens / 1_000_000 * 6.25
        + total_cache_read_tokens / 1_000_000 * 0.50
        + total_output_tokens / 1_000_000 * PRICE_OUTPUT
    )
    results["__usage__"] = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_creation_tokens": total_cache_creation_tokens,
        "cache_read_tokens": total_cache_read_tokens,
        "actual_cost": round(actual_cost, 4),
    }
    return results


def report_to_notion(actual_cost, emails_processed):
    """Update AI Model Decisions page with run stats."""
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("   ⚠️  אין NOTION_TOKEN — מדלג על עדכון Notion")
        return
    try:
        resp = http_requests.patch(
            f"https://api.notion.com/v1/pages/{NOTION_PAGE_ID}",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "properties": {
                    "עלות בפועל": {"number": round(actual_cost, 4)},
                    "ריצה אחרונה": {
                        "date": {"start": datetime.now().date().isoformat()}
                    },
                    "פריטים בריצה אחרונה": {"number": emails_processed},
                }
            },
        )
        resp.raise_for_status()
        print(f"   ✅ Notion עודכן → https://www.notion.so/{NOTION_PAGE_ID.replace('-', '')}")
    except Exception as exc:
        print(f"   ⚠️  שגיאה בעדכון Notion: {exc}")


def _parse_json_response(text):
    """Parse JSON from Claude's response, handling code fences."""
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        clean = clean.rsplit("```", 1)[0]
    try:
        data = json.loads(clean)
        return {"status": "success", "data": data}
    except json.JSONDecodeError:
        return {"status": "parse_error", "raw": text}


# ─── Main ─────────────────────────────────────────────────────


def main():
    parser = ArgumentParser(description="סוכן מענה אישי — Batch Processor")
    parser.add_argument(
        "--resume", action="store_true", help="המשך מ-batch קיים"
    )
    parser.add_argument(
        "--drafts-only",
        action="store_true",
        help="רק יצירת טיוטות מתוצאות קיימות",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="הכל חוץ מיצירת טיוטות בפועל",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="מספר מיילים מקסימלי (לבדיקה)",
    )
    parser.add_argument(
        "--use-existing-emails",
        action="store_true",
        help="השתמש ב-emails.json קיים במקום שליפה מחדש",
    )
    parser.add_argument(
        "--tag-sent",
        action="store_true",
        help="העבר את כל מה שנשלח מ-VIP ל-VIP-נענו (חד פעמי)",
    )
    parser.add_argument(
        "--send-drafts",
        action="store_true",
        help="שלח את כל הטיוטות שנוצרו בריצה האחרונה",
    )
    parser.add_argument(
        "--cleanup-drafts",
        action="store_true",
        help="מחק מ-Gmail טיוטות שסומנו לבדיקה-מיוחדת",
    )
    parser.add_argument(
        "--delete-all-drafts",
        action="store_true",
        help="מחק את כל הטיוטות מהריצה האחרונה",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("🤖 סוכן מענה אישי — Batch Processor")
    print(f"   Model: {MODEL}")
    if args.dry_run:
        print("   ⚠️  DRY RUN — לא ייווצרו טיוטות")
    if args.limit:
        print(f"   ⚠️  LIMIT — רק {args.limit} מיילים")
    print("=" * 50)

    if args.tag_sent:
        if not DRAFTS_FILE.exists():
            sys.exit("❌ לא נמצא drafts_report.json")
        report = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
        threads = report["details"]["drafts"]
        print(f"\n🏷️  מעביר {len(threads)} שרשורים מ-VIP ל-VIP-נענו...")
        token = get_gmail_token()
        vip_id = get_label_id(token, "VIP")
        vip_answered_id = get_label_id(token, "VIP/VIP-נענו")
        if not vip_answered_id:
            sys.exit("❌ תווית 'VIP/VIP-נענו' לא נמצאה — צרי אותה ב-Gmail קודם")
        done, errors = 0, 0
        for d in threads:
            try:
                modify_thread_labels(
                    token, d["id"],
                    add_labels=[vip_answered_id],
                    remove_labels=[vip_id] if vip_id else None,
                )
                print(f"   ✅ {d['from'][:45]}")
                done += 1
            except Exception as exc:
                print(f"   ❌ {d['from'][:35]} — {exc}")
                errors += 1
        print(f"\n✅ הועברו {done} | ❌ שגיאות: {errors}")
        return

    if args.send_drafts:
        token = get_gmail_token()
        vip_id = get_label_id(token, "VIP")
        vip_answered_id = get_label_id(token, "VIP/VIP-נענו")
        print(f"   🏷️  VIP: {vip_id} | VIP-נענו: {vip_answered_id}")

        # שולף את כל הטיוטות בשרשורי VIP (לא רק מהריצה האחרונה)
        print("📋 סורק טיוטות בשרשורי VIP...")
        all_drafts_resp = http_requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Authorization": f"Bearer {token}"},
            params={"maxResults": 500},
        )
        all_drafts_resp.raise_for_status()
        all_drafts = all_drafts_resp.json().get("drafts", [])

        to_send = []
        for d in all_drafts:
            info = http_requests.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{d['id']}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "metadata", "metadataHeaders": ["To", "From", "Subject"]},
            ).json()
            msg = info["message"]
            tid = msg["threadId"]
            hdrs = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
            thread = http_requests.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{tid}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "minimal"},
            ).json()
            thread_labels = thread.get("messages", [{}])[0].get("labelIds", []) if thread.get("messages") else []
            if vip_id and vip_id in thread_labels:
                to_send.append({
                    "draft_id": d["id"],
                    "thread_id": tid,
                    "from": hdrs.get("to", ""),
                })

        if not to_send:
            print("✅ אין טיוטות VIP לשליחה")
            return

        print(f"\n📤 שולח {len(to_send)} טיוטות VIP...")
        sent, errors = 0, 0
        for d in to_send:
            try:
                resp = http_requests.post(
                    "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"id": d["draft_id"]},
                )
                if resp.status_code == 404:
                    print(f"   ⏭️  דולג (נמחק): {d['from'][:45]}")
                    continue
                resp.raise_for_status()
                print(f"   ✅ נשלח: {d['from'][:45]}")
                sent += 1
                try:
                    modify_thread_labels(
                        token, d["thread_id"],
                        add_labels=[vip_answered_id] if vip_answered_id else None,
                        remove_labels=[vip_id] if vip_id else None,
                    )
                except Exception:
                    pass
            except Exception as exc:
                print(f"   ❌ שגיאה: {d['from'][:35]} — {exc}")
                errors += 1
        print(f"\n✅ נשלחו {sent} מיילים | ❌ שגיאות: {errors}")
        return

    if args.delete_all_drafts:
        if not DRAFTS_FILE.exists():
            sys.exit("❌ לא נמצא drafts_report.json")
        report = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
        to_delete = report["details"]["drafts"]
        if not to_delete:
            print("✅ אין טיוטות למחיקה")
            return
        print(f"\n🗑️  מוחק {len(to_delete)} טיוטות...")
        token = get_gmail_token()
        deleted, skipped, errors = 0, 0, 0
        for d in to_delete:
            try:
                resp = http_requests.delete(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{d['draft_id']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 404:
                    skipped += 1
                else:
                    resp.raise_for_status()
                    deleted += 1
            except Exception as exc:
                print(f"   ❌ שגיאה: {d['from'][:35]} — {exc}")
                errors += 1
        print(f"\n✅ נמחקו {deleted} | ⏭️ כבר נשלחו/נמחקו: {skipped} | ❌ שגיאות: {errors}")
        return

    if args.cleanup_drafts:
        if not DRAFTS_FILE.exists():
            sys.exit("❌ לא נמצא drafts_report.json")
        report = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
        to_delete = [
            d for d in report["details"]["drafts"]
            if d.get("category") == "לבדיקה-מיוחדת"
        ]
        if not to_delete:
            print("✅ אין טיוטות לבדיקה-מיוחדת למחיקה")
            return
        print(f"\n🗑️  מוחק {len(to_delete)} טיוטות לבדיקה-מיוחדת...")
        token = get_gmail_token()
        deleted, errors = 0, 0
        for d in to_delete:
            try:
                resp = http_requests.delete(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{d['draft_id']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                print(f"   🗑️  נמחק: {d['from'][:45]}")
                deleted += 1
            except Exception as exc:
                print(f"   ❌ שגיאה: {d['from'][:35]} — {exc}")
                errors += 1
        print(f"\n✅ נמחקו {deleted} טיוטות | ❌ שגיאות: {errors}")
        return

    # ── Verify credentials ──
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("❌ חסר ANTHROPIC_API_KEY ב-.env")

    # ── Load instructions ──
    print("\n📄 טוען הוראות...")
    if not INSTRUCTIONS_FILE.exists():
        sys.exit(f"❌ לא נמצא קובץ הוראות: {INSTRUCTIONS_FILE}")
    if not GUIDES_FILE.exists():
        sys.exit(f"❌ לא נמצא קטלוג מדריכים: {GUIDES_FILE}")

    instructions = INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    guides = GUIDES_FILE.read_text(encoding="utf-8")
    print(f"   הוראות: {len(instructions):,} תווים")
    print(f"   קטלוג: {len(guides):,} תווים")

    # ── Step 1: Fetch or load emails ──
    if args.drafts_only:
        if not EMAILS_FILE.exists() or not RESULTS_FILE.exists():
            sys.exit("❌ --drafts-only דורש emails.json ו-results.json קיימים")
        emails = json.loads(EMAILS_FILE.read_text(encoding="utf-8"))
        results = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        print(
            f"\n📧 נטען מקובץ: {len(emails)} מיילים, "
            f"{len(results)} תוצאות"
        )
    else:
        if EMAILS_FILE.exists() and not args.resume and args.use_existing_emails:
            emails = json.loads(EMAILS_FILE.read_text(encoding="utf-8"))
            print(f"\n📧 שימוש בקובץ קיים: {len(emails)} מיילים")
        elif not args.resume:
            print("\n📧 שולף מיילים מ-Gmail (VIP)...")
            token = get_gmail_token()
            emails = fetch_vip_emails(token, limit=args.limit)
            EMAILS_FILE.write_text(
                json.dumps(emails, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            if not EMAILS_FILE.exists():
                sys.exit("❌ --resume דורש emails.json קיים")
            emails = json.loads(EMAILS_FILE.read_text(encoding="utf-8"))

        print(f"   סה\"כ: {len(emails)} מיילים")

        # ── Group by thread ──
        threads = group_by_thread(emails)
        multi = sum(1 for t in threads.values() if len(t) > 1)
        print(f"   שרשורים: {len(threads)} ({multi} עם יותר מהודעה אחת)")

        # ── Step 2: Submit or resume batch ──
        if args.resume and STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            batch_id = state["batch_id"]
            print(f"\n🔄 ממשיך batch: {batch_id}")
            client = anthropic.Anthropic()
            results = poll_batch(client, batch_id)
        else:
            items = build_batch(threads, instructions, guides)
            results = submit_batch(items)

        RESULTS_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 תוצאות נשמרו: {RESULTS_FILE}")

    # ── Step 3: Create reply drafts ──
    # In drafts_only mode, emails were loaded from file — group here
    if args.drafts_only:
        threads = group_by_thread(emails)

    # latest email per thread — used for creating the reply draft
    thread_latest = {
        tid: sorted(msgs, key=lambda e: int(e.get("internalDate", "0")))[-1]
        for tid, msgs in threads.items()
    }

    if args.dry_run:
        print("\n⚠️  DRY RUN — מדלג על יצירת טיוטות")
        _print_dry_run_summary(emails, threads, results)
        usage = results.get("__usage__", {})
        print("\n📡 מעדכן Notion...")
        report_to_notion(usage.get("actual_cost", 0), len(threads))
        return

    print("\n📝 יוצר טיוטות reply ב-Gmail...")
    token = get_gmail_token()
    created, skipped_list, errors = [], [], []

    for tid, res in results.items():
        if tid == "__usage__":
            continue

        em = thread_latest.get(tid)
        if not em:
            errors.append({"id": tid, "error": "thread not found"})
            continue

        if res["status"] != "success":
            errors.append(
                {
                    "id": tid,
                    "from": em["from"],
                    "error": res.get("error", res.get("raw", "?"))[:200],
                }
            )
            print(f"   ❌ שגיאה: {em['from'][:35]}")
            continue

        d = res["data"]
        if d.get("skip"):
            skipped_list.append(
                {
                    "id": tid,
                    "from": em["from"],
                    "reason": d.get("skip_reason", ""),
                }
            )
            print(
                f"   ⏭️  דילוג: {em['from'][:35]} — "
                f"{d.get('skip_reason', '')}"
            )
            continue

        try:
            draft = create_reply_draft(token, em, d["reply_text"])
            created.append(
                {
                    "id": tid,
                    "from": em["from"],
                    "draft_id": draft["id"],
                    "category": d.get("category", ""),
                    "thread_size": len(threads.get(tid, [em])),
                }
            )
            thread_size = len(threads.get(tid, [em]))
            size_note = f" ({thread_size} הודעות)" if thread_size > 1 else ""
            print(
                f"   ✅ טיוטה{size_note}: {em['from'][:35]} "
                f"[{d.get('category', '')}]"
            )
        except Exception as exc:
            errors.append(
                {"id": tid, "from": em["from"], "error": str(exc)[:200]}
            )
            print(f"   ❌ שגיאה ב-Gmail: {em['from'][:35]} — {exc}")

    # ── Cost reporting ──
    usage = results.get("__usage__", {})
    actual_cost = usage.get("actual_cost", 0)
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_creation = usage.get("cache_creation_tokens", 0)
    cache_read = usage.get("cache_read_tokens", 0)

    # ── Save report ──
    report = {
        "run_date": datetime.now().isoformat(),
        "model": MODEL,
        "total_emails": len(emails),
        "drafts_created": len(created),
        "skipped": len(skipped_list),
        "errors": len(errors),
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "actual_cost_usd": actual_cost,
        },
        "details": {
            "drafts": created,
            "skipped": skipped_list,
            "errors": errors,
        },
    }
    DRAFTS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _print_summary(len(emails), len(threads), len(created), len(skipped_list),
                   len(errors), actual_cost, input_tokens, output_tokens,
                   cache_creation, cache_read)

    # ── Notion update ──
    print("\n📡 מעדכן Notion...")
    report_to_notion(actual_cost, len(threads))


def _print_dry_run_summary(emails, threads, results):
    """Print summary without creating drafts."""
    success = sum(
        1
        for rid, r in results.items()
        if rid != "__usage__" and r["status"] == "success" and not r["data"].get("skip")
    )
    skip = sum(
        1
        for rid, r in results.items()
        if rid != "__usage__" and r["status"] == "success" and r["data"].get("skip")
    )
    err = sum(
        1 for rid, r in results.items()
        if rid != "__usage__" and r["status"] != "success"
    )
    usage = results.get("__usage__", {})
    actual_cost = usage.get("actual_cost", 0)
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_creation = usage.get("cache_creation_tokens", 0)
    cache_read = usage.get("cache_read_tokens", 0)

    print("\n" + "=" * 50)
    print("📊 סיכום (DRY RUN)")
    print("=" * 50)
    print(f"   📧 סה\"כ מיילים:        {len(emails)}")
    print(f"   🧵 שרשורים:            {len(threads)}")
    print(f"   ✅ טיוטות שהיו נוצרות: {success}")
    print(f"   ⏭️  דולגו:              {skip}")
    print(f"   ❌ שגיאות:             {err}")
    print(f"\n   🪙 עלות הריצה:")
    print(f"      Input tokens:         {input_tokens:,}")
    print(f"      Cache creation tokens:{cache_creation:,}")
    print(f"      Cache read tokens:    {cache_read:,}")
    print(f"      Output tokens:        {output_tokens:,}")
    print(f"      💵 סה\"כ:              ${actual_cost:.4f}")
    print("=" * 50)


def _print_summary(total_emails, total_threads, created, skipped, errors,
                   actual_cost=0, input_tokens=0, output_tokens=0,
                   cache_creation=0, cache_read=0):
    print("\n" + "=" * 50)
    print("📊 סיכום")
    print("=" * 50)
    print(f"   📧 סה\"כ מיילים:  {total_emails}")
    print(f"   🧵 שרשורים:      {total_threads}")
    print(f"   ✅ טיוטות נוצרו: {created}")
    print(f"   ⏭️  דולגו:        {skipped}")
    print(f"   ❌ שגיאות:       {errors}")
    print(f"\n   🪙 עלות הריצה:")
    print(f"      Input tokens:         {input_tokens:,}")
    print(f"      Cache creation tokens:{cache_creation:,}")
    print(f"      Cache read tokens:    {cache_read:,}")
    print(f"      Output tokens:        {output_tokens:,}")
    print(f"      💵 סה\"כ:              ${actual_cost:.4f}")
    print(f"\n   📄 דוח: {DRAFTS_FILE}")
    print("=" * 50)


if __name__ == "__main__":
    main()
