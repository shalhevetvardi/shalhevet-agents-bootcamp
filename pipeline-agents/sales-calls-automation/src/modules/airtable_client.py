"""
מודול לעבודה מול Airtable — CRUD, שליפה, והתאמת לידים לפי טלפון.
"""
import os
import json
import logging
import re
from email.utils import parsedate_to_datetime
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

log = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """
    מנרמל מספר טלפון לפורמט E.164 ישראלי: +972XXXXXXXXX
    מקבל: 050-1234567 / 0501234567 / +972501234567 / 972501234567
    מחזיר: +972501234567
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("972"):
        return "+" + digits
    if digits.startswith("0"):
        return "+972" + digits[1:]
    if digits.startswith("+"):
        return digits
    return "+" + digits if digits else ""


class AirtableClient:
    def __init__(self, api_key: str, base_id: str, table_id: str, config_path: str):
        self.api_key = api_key
        self.base_id = base_id
        self.table_id = table_id
        self.base_url = f"https://api.airtable.com/v0/{base_id}/{table_id}"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        self.fields = cfg["airtable"]["fields"]

    # ---------- קריאה ----------
    def list_all_records(self, by_id: bool = False) -> List[Dict[str, Any]]:
        """שולף את כל הרשומות בטבלה (עם paginate אוטומטי).
        by_id=True יחזיר שדות לפי field_id במקום display name.
        """
        records = []
        offset = None
        while True:
            params = {"pageSize": 100}
            if by_id:
                params["returnFieldsByFieldId"] = "true"
            if offset:
                params["offset"] = offset
            r = requests.get(self.base_url, headers=self.headers, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return records

    def get_record(self, record_id: str) -> Dict[str, Any]:
        """שולף רשומה בודדת לפי ID (עם display names)."""
        url = f"{self.base_url}/{record_id}"
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """מחפש רשומה לפי מספר טלפון מנורמל. מחזיר את הראשונה או None."""
        target = normalize_phone(phone)
        if not target:
            return None
        for rec in self.list_all_records():
            rec_phone = rec.get("fields", {}).get("טלפון", "")
            if normalize_phone(rec_phone) == target:
                return rec
        return None

    def find_by_calendly_uri(self, uri: str) -> Optional[Dict[str, Any]]:
        """בדיקת כפילות — האם האירוע הזה מקלנדלי כבר קיים."""
        for rec in self.list_all_records():
            if rec.get("fields", {}).get("Calendly URI") == uri:
                return rec
        return None

    def find_by_call_sid(self, sid: str) -> Optional[Dict[str, Any]]:
        """בדיקת כפילות — האם ה-Call SID מופיע בשדה של כלשהי מהרשומות.
        תומך ברשימה מופרדת בפסיקים (ריבוי שיחות לליד אחד).
        """
        if not sid:
            return None
        for rec in self.list_all_records():
            stored = rec.get("fields", {}).get("Twilio Call SID", "") or ""
            if sid in stored:  # substring match — תופס גם ערך יחיד וגם רשימה מופרדת בפסיקים
                return rec
        return None

    def find_unclaimed_lead_near(self, iso_datetime: str, hours: float = 2) -> Optional[Dict[str, Any]]:
        """מחפש ליד בלי Call SID שיש לו call_datetime בטווח ±hours סביב iso_datetime.
        מחזיר את הרשומה עם display names (דרך get_record).
        """
        if not iso_datetime:
            return None
        try:
            target = self._parse_twilio_datetime(iso_datetime)
        except Exception as e:
            log.warning("find_unclaimed_lead_near: bad iso_datetime '%s': %s", iso_datetime, e)
            return None
        if not target:
            return None

        dt_field_id = self.fields["call_datetime"]
        sid_field_id = self.fields["twilio_call_sid"]
        best_id: Optional[str] = None
        best_delta = timedelta(hours=hours)

        try:
            records = self.list_all_records(by_id=True)
        except Exception as e:
            log.warning("find_unclaimed_lead_near: list failed: %s", e)
            return None

        for rec in records:
            fields = rec.get("fields", {})
            if fields.get(sid_field_id):  # יש כבר Call SID — לא זמין
                continue
            dt_str = fields.get(dt_field_id)
            if not dt_str:
                continue
            try:
                dt = self._parse_twilio_datetime(dt_str)
            except Exception:
                continue
            if not dt:
                continue
            delta = abs(dt - target)
            if delta <= best_delta:
                best_delta = delta
                best_id = rec.get("id")

        if best_id:
            try:
                return self.get_record(best_id)
            except Exception as e:
                log.warning("get_record failed for %s: %s", best_id, e)
        return None

    def append_call_sid(self, existing: str, new_sid: str) -> str:
        """מצרף Call SID לרשימה קיימת (ללא כפילויות)."""
        sids = [s.strip() for s in (existing or "").split(",") if s.strip()]
        if new_sid and new_sid not in sids:
            sids.append(new_sid)
        return ", ".join(sids)

    def _parse_twilio_datetime(self, value: str) -> Optional[datetime]:
        """מפרסר תאריכי Twilio (RFC2822) וגם ISO, ומחזיר זמן aware ב-UTC."""
        if not value:
            return None
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ---------- כתיבה ----------
    def create_record(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """יוצר רשומה חדשה. fields = {field_id: value}"""
        payload = {"fields": fields, "typecast": True}
        r = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)
        if r.status_code >= 400:
            log.error("Airtable create failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """מעדכן רשומה קיימת. fields = {field_id: value}"""
        url = f"{self.base_url}/{record_id}"
        payload = {"fields": fields, "typecast": True}
        r = requests.patch(url, headers=self.headers, json=payload, timeout=30)
        if r.status_code >= 400:
            log.error("Airtable update failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        return r.json()

    # ---------- עזרים ----------
    def f(self, key: str) -> str:
        """מחזיר field_id לפי שם לוגי מה-config."""
        return self.fields[key]
