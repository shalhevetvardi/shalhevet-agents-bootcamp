"""
Pipeline A — Calendly → Airtable
שולף אירועים מ-Calendly (גם מאושרים וגם עתידיים), ומכניס לידים חדשים ל-Airtable.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import requests

from .airtable_client import AirtableClient, normalize_phone

log = logging.getLogger(__name__)

# מילות מפתח להכרת שדה טלפון בשאלת Calendly — עברית + אנגלית + שגיאות הקלדה נפוצות
PHONE_KEYWORDS = [
    "phone", "mobile", "cell", "tel", "contact",
    "טלפון", "נייד", "סלולרי", "סלולארי", "מספר", "ליצירת קשר",
    "pone", "phon",  # typos
]

# fallback — רצף של 9-10 ספרות (אפשר עם רווחים, מקפים, סוגריים ו-+)
PHONE_REGEX = re.compile(r"(?:\+?\d[\d\-\s()]{7,14}\d)")


def _extract_phone_from_qa(qa_list: List[Dict[str, Any]]) -> str:
    """מחלץ טלפון משאלות-ותשובות של Calendly.
    שלב 1: מתאים לפי מילת מפתח בשאלה.
    שלב 2 (fallback): סורק כל תשובה אחר רצף ספרות בפורמט טלפון.
    """
    # שלב 1 — לפי מילת מפתח בשאלה
    for qa in qa_list or []:
        q = (qa.get("question", "") or "").lower()
        if any(k in q for k in PHONE_KEYWORDS):
            answer = (qa.get("answer", "") or "").strip()
            if answer:
                return answer
    # שלב 2 — fallback רגקס על כל התשובות
    for qa in qa_list or []:
        answer = (qa.get("answer", "") or "").strip()
        if not answer:
            continue
        m = PHONE_REGEX.search(answer)
        if m:
            candidate = m.group(0)
            # וידוא שיש מספיק ספרות (9+) — למנוע חיובי שגוי על מספרי שנה/גיל
            digits_only = re.sub(r"\D", "", candidate)
            if len(digits_only) >= 9:
                return candidate
    return ""


class CalendlySync:
    def __init__(self, api_token: str, user_uri: str, airtable: AirtableClient, config: dict):
        self.token = api_token
        self.user_uri = user_uri
        self.airtable = airtable
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def list_events(self, min_start: datetime, max_start: datetime) -> List[Dict[str, Any]]:
        """שולף אירועים בטווח זמן."""
        url = "https://api.calendly.com/scheduled_events"
        events = []
        page_token = None
        while True:
            params = {
                "user": self.user_uri,
                "min_start_time": min_start.isoformat(),
                "max_start_time": max_start.isoformat(),
                "count": 100,
                "status": "active",
            }
            if page_token:
                params["page_token"] = page_token
            r = requests.get(url, headers=self.headers, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            events.extend(data.get("collection", []))
            pg = data.get("pagination", {})
            page_token = pg.get("next_page_token")
            if not page_token:
                break
        return events

    def list_invitees(self, event_uri: str) -> List[Dict[str, Any]]:
        """שולף את המוזמנים לאירוע."""
        url = f"{event_uri}/invitees"
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json().get("collection", [])

    def run(self) -> Dict[str, int]:
        """
        הרצה אחת: שולף אירועים ומכניס לידים חדשים.
        מחזיר סטטיסטיקות: {'created': N, 'skipped': M, 'errors': K}
        """
        stats = {"created": 0, "skipped": 0, "errors": 0}
        now = datetime.now(timezone.utc)
        min_start = now - timedelta(days=self.config["pipeline"]["calendly_lookback_days"])
        max_start = now + timedelta(days=self.config["pipeline"]["calendly_lookahead_days"])

        try:
            events = self.list_events(min_start, max_start)
            log.info("Calendly: found %d events", len(events))
        except Exception as e:
            log.exception("Calendly list_events failed: %s", e)
            stats["errors"] += 1
            return stats

        for ev in events:
            ev_uri = ev.get("uri")
            if not ev_uri:
                continue

            # בדיקת כפילות לפי Calendly URI
            if self.airtable.find_by_calendly_uri(ev_uri):
                stats["skipped"] += 1
                continue

            try:
                invitees = self.list_invitees(ev_uri)
            except Exception as e:
                log.warning("Failed to fetch invitees for %s: %s", ev_uri, e)
                stats["errors"] += 1
                continue

            for inv in invitees:
                # בדיקה: האם המוזמן ביטל?
                if inv.get("status") == "canceled":
                    continue

                name = inv.get("name", "") or "לא ידוע"
                email = inv.get("email", "")
                # טלפון בד״כ נמצא ב-questions_and_answers או ב-text_reminder_number
                phone = inv.get("text_reminder_number", "") or ""
                if not phone:
                    phone = _extract_phone_from_qa(inv.get("questions_and_answers", []))

                phone = normalize_phone(phone)
                if not phone:
                    log.warning(
                        "No phone extracted for %s (%s) — lead will be created without phone",
                        name, email or "no-email",
                    )

                # נסה להתאים לרשומה קיימת לפי טלפון — אם יש, פשוט עדכן עם ה-Calendly URI
                existing = self.airtable.find_by_phone(phone) if phone else None
                if existing:
                    try:
                        self.airtable.update_record(
                            existing["id"],
                            {
                                self.airtable.f("calendly_uri"): ev_uri,
                                self.airtable.f("call_datetime"): ev.get("start_time"),
                                self.airtable.f("email"): email or existing["fields"].get("Email", ""),
                            },
                        )
                        stats["skipped"] += 1  # לא חדש, רק עדכון
                        log.info("Updated existing lead by phone: %s", phone)
                    except Exception as e:
                        log.exception("Update failed: %s", e)
                        stats["errors"] += 1
                    continue

                # יצירת ליד חדש
                try:
                    fields = {
                        self.airtable.f("name"): name,
                        self.airtable.f("phone"): phone,
                        self.airtable.f("email"): email,
                        self.airtable.f("calendly_uri"): ev_uri,
                        self.airtable.f("call_datetime"): ev.get("start_time"),
                        self.airtable.f("status"): "חדש",
                    }
                    self.airtable.create_record(fields)
                    stats["created"] += 1
                    log.info("Created new lead: %s (%s)", name, phone)
                except Exception as e:
                    log.exception("Create failed for %s: %s", name, e)
                    stats["errors"] += 1

        log.info("Calendly sync done: %s", stats)
        return stats
