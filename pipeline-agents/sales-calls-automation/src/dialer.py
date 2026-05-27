#!/usr/bin/env python3
"""
dialer.py — חייגן לוקאלי לשיחות מכירה עם הקלטה אוטומטית.

פותח שרת HTTP מקומי + דפדפן. מציג לידים מקלנדלי.
לחיצה על "חייג" → טוויליו מחייג לאייפון, ומחבר אל הליד כשעונים, עם הקלטה מלאה.
ההקלטה מופיעה אוטומטית ב-Twilio Recordings — הפייפליין הרגיל יקלוט אותה תוך 5 דק'.
"""
import os
import re
import sys
import json
import socket
import threading
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

PORT = 8765
HTML_FILE = SCRIPT_DIR / "dialer.html"

# משתני סביבה
TWILIO_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_NUM = os.environ["TWILIO_PHONE_NUMBER"]
USER_CELL = os.environ["USER_CELL_PHONE"]
CALENDLY_TOKEN = os.environ["CALENDLY_API_TOKEN"]
CALENDLY_USER = os.environ["CALENDLY_USER_URI"]


def normalize_phone(phone: str) -> str:
    """המרה לפורמט E.164 (ישראל)."""
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    elif phone.startswith("0"):
        phone = "+972" + phone[1:]
    elif not phone.startswith("+"):
        phone = "+" + phone
    return phone


# רגקס לזיהוי מספרי טלפון ישראליים ובינלאומיים בטקסט חופשי
_PHONE_RE = re.compile(
    r'(?:\+?972[\s\-]?\d{1,2}[\s\-]?\d{3}[\s\-]?\d{4}'        # +972 54-760-8896
    r'|0\d[\s\-]?\d{3}[\s\-]?\d{4}'                             # 054-760-8896
    r'|\+\d{1,3}[\s\-]?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4})'    # generic international
)

_PHONE_KEYWORDS = [
    "phone", "טלפון", "נייד", "פלאפון", "מובייל", "mobile",
    "להתקשר", "מס'", "מס׳", "מספר", "call", "number", "telephone",
]


def extract_phone_from_text(text: str) -> str:
    """חיפוש רצף שנראה כמו מספר טלפון בתוך טקסט חופשי."""
    if not text:
        return ""
    m = _PHONE_RE.search(text)
    return m.group(0) if m else ""


def find_invitee_phone(invitee: dict, event: dict) -> str:
    """
    חיפוש מספר טלפון במקורות אפשריים — לפי סדר העדיפות:
    1. text_reminder_number (שדה רשמי)
    2. תשובות לשאלות עם מילת מפתח של טלפון
    3. שדה Location של האירוע (לאירועי phone_call)
    4. סריקת רגקס על כל התשובות
    """
    # 1. שדה רשמי
    phone = invitee.get("text_reminder_number") or ""
    if phone:
        return phone

    # 2. Q&A עם מילות מפתח
    qas = invitee.get("questions_and_answers") or []
    for qa in qas:
        q = (qa.get("question") or "").lower()
        if any(k in q for k in _PHONE_KEYWORDS):
            ans = qa.get("answer") or ""
            extracted = extract_phone_from_text(ans)
            if extracted:
                return extracted
            if ans.strip():
                return ans.strip()

    # 3. Location של האירוע (Calendly מזין שם מספר באירועי phone_call)
    location = event.get("location") or {}
    loc_candidates = []
    if isinstance(location, dict):
        loc_candidates.append(location.get("location") or "")
        loc_candidates.append(location.get("additional_info") or "")
    elif isinstance(location, str):
        loc_candidates.append(location)
    for loc in loc_candidates:
        extracted = extract_phone_from_text(loc)
        if extracted:
            return extracted

    # 4. סריקת רגקס על כל התשובות
    for qa in qas:
        ans = qa.get("answer") or ""
        extracted = extract_phone_from_text(ans)
        if extracted:
            return extracted

    return ""


def fetch_calendly_leads():
    """שליפת פגישות עתידיות ואחרונות מקלנדלי עם פרטי הלידים."""
    import requests

    now = datetime.now(timezone.utc)
    min_time = (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    max_time = (now + timedelta(days=30)).isoformat().replace("+00:00", "Z")

    headers = {"Authorization": f"Bearer {CALENDLY_TOKEN}"}

    r = requests.get(
        "https://api.calendly.com/scheduled_events",
        headers=headers,
        params={
            "user": CALENDLY_USER,
            "status": "active",
            "min_start_time": min_time,
            "max_start_time": max_time,
            "count": 50,
            "sort": "start_time:asc",
        },
        timeout=20,
    )
    r.raise_for_status()
    events = r.json().get("collection", [])

    leads = []
    for event in events:
        event_uri = event["uri"]

        inv_r = requests.get(
            f"{event_uri}/invitees",
            headers=headers,
            timeout=20,
        )
        inv_r.raise_for_status()
        invitees = inv_r.json().get("collection", [])

        for inv in invitees:
            phone = find_invitee_phone(inv, event)

            leads.append({
                "name": inv.get("name") or "ללא שם",
                "email": inv.get("email") or "",
                "phone": phone,
                "start_time": event.get("start_time"),
                "event_name": event.get("name") or "",
                "status": inv.get("status") or "active",
            })

    return leads


def initiate_call(lead_name: str, lead_phone: str) -> dict:
    """
    יוזמת שיחה דו-צדדית מוקלטת:
    1. טוויליו מחייגת לסלולרי של שלהבת
    2. כשעונים — TwiML מפעיל <Dial> אל הליד עם record
    3. הקלטה אחת מלאה נשמרת ב-Twilio Recordings
    """
    from twilio.rest import Client

    phone = normalize_phone(lead_phone)

    # TwiML inline — אין צורך ב-URL ציבורי
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response>'
        f'<Say language="he-IL">מחבר את שיחת המכירה עם {lead_name}</Say>'
        f'<Dial record="record-from-answer" callerId="{TWILIO_NUM}" timeout="30">'
        f'<Number>{phone}</Number>'
        '</Dial>'
        '</Response>'
    )

    client = Client(TWILIO_SID, TWILIO_TOKEN)
    call = client.calls.create(
        to=USER_CELL,
        from_=TWILIO_NUM,
        twiml=twiml,
    )

    return {
        "call_sid": call.sid,
        "status": call.status,
        "lead_name": lead_name,
        "lead_phone": phone,
    }


class DialerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # שקט בטרמינל
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            if not HTML_FILE.exists():
                self._send_json(500, {"ok": False, "error": "dialer.html לא נמצא"})
                return
            body = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/leads":
            try:
                leads = fetch_calendly_leads()
                self._send_json(200, {"ok": True, "leads": leads})
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)[:300]})
            return

        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/call":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(raw)
                name = data.get("name", "") or "ליד"
                phone = data.get("phone", "")
                if not phone:
                    self._send_json(400, {"ok": False, "error": "חסר מספר טלפון"})
                    return
                result = initiate_call(name, phone)
                self._send_json(200, {"ok": True, "result": result})
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)[:300]})
            return

        self._send_json(404, {"ok": False, "error": "not found"})


def find_free_port(preferred: int) -> int:
    """חיפוש פורט פנוי — אם preferred תפוס, מחפש את הבא."""
    for p in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("לא נמצא פורט פנוי")


def main():
    port = find_free_port(PORT)

    print("=" * 60)
    print(f"  📞  חייגן אִימפּרוּב")
    print("=" * 60)
    print()
    if port != PORT:
        print(f"ℹ️  הפורט {PORT} תפוס — עובר ל-{port}")
    print(f"▶ שרת רץ על http://localhost:{port}")
    print(f"▶ לסגירה: Ctrl+C")
    print()

    # פתיחת דפדפן רק אחרי שהשרת מוכן (מהשנייה ה-0.8 ואילך)
    def open_browser():
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            pass

    threading.Timer(0.8, open_browser).start()

    server = HTTPServer(("127.0.0.1", port), DialerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  עוצרת")
        server.shutdown()


if __name__ == "__main__":
    main()
