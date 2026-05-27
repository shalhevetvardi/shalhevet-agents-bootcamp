"""
Pipeline B — Twilio → תמלול → ניתוח → טיוטת מייל
"""
import os
import logging
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import requests
from requests.auth import HTTPBasicAuth

from .airtable_client import AirtableClient, normalize_phone

log = logging.getLogger(__name__)


class TwilioSync:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        my_number: str,
        my_personal_number: str,
        airtable: AirtableClient,
        transcriber,
        analyzer,
        email_drafter,
        config: dict,
    ):
        self.sid = account_sid
        self.token = auth_token
        self.my_number = my_number
        self.my_personal_number = my_personal_number
        self.airtable = airtable
        self.transcriber = transcriber
        self.analyzer = analyzer
        self.email_drafter = email_drafter
        self.config = config
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"
        self.auth = HTTPBasicAuth(account_sid, auth_token)

    def list_recordings(self, lookback_hours: int) -> List[Dict[str, Any]]:
        """שולף הקלטות מה-N שעות האחרונות."""
        after = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        recordings = []
        url = f"{self.base_url}/Recordings.json"
        params = {
            "DateCreated>": after.strftime("%Y-%m-%d"),
            "PageSize": 100,
        }
        while url:
            r = requests.get(url, auth=self.auth, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            recordings.extend(data.get("recordings", []))
            next_uri = data.get("next_page_uri")
            url = f"https://api.twilio.com{next_uri}" if next_uri else None
            params = None
        return recordings

    def get_call(self, call_sid: str) -> Dict[str, Any]:
        """שולף פרטי שיחה מ-Twilio."""
        r = requests.get(
            f"{self.base_url}/Calls/{call_sid}.json",
            auth=self.auth,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def download_recording(self, recording_sid: str, target_path: str) -> str:
        """מוריד הקלטה כ-mp3."""
        url = f"{self.base_url}/Recordings/{recording_sid}.mp3"
        r = requests.get(url, auth=self.auth, timeout=120, stream=True)
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return target_path

    def _get_lead_phone(self, call: Dict[str, Any]) -> Optional[str]:
        """
        שולף את מספר הטלפון של הלקוח — הצד שאינו שייך לי.
        שכבה 1: בודק from/to של השיחה עצמה.
        שכבה 2: אם שני הצדדים שלי (שיחת עיגן) — בודק child calls של Twilio,
        כי עיגן יוצר child call עם מספר הליד האמיתי.
        """
        mine = {
            normalize_phone(self.my_number),
            normalize_phone(self.my_personal_number),
        }

        from_num = normalize_phone(call.get("from", ""))
        to_num = normalize_phone(call.get("to", ""))
        for num in (from_num, to_num):
            if num and num not in mine:
                return num

        call_sid = call.get("sid")
        if not call_sid:
            return None
        try:
            r = requests.get(
                f"{self.base_url}/Calls.json",
                auth=self.auth,
                params={"ParentCallSid": call_sid, "PageSize": 5},
                timeout=30,
            )
            r.raise_for_status()
            children = r.json().get("calls", [])
            for child in children:
                for num in (normalize_phone(child.get("to", "")),
                            normalize_phone(child.get("from", ""))):
                    if num and num not in mine:
                        log.info("Lead phone from child call: %s", num)
                        return num
        except Exception as e:
            log.warning("Failed to fetch child calls for %s: %s", call_sid, e)

        return None

    def _save_recording_copy(
        self, audio_path: str, call_sid: str,
        start_time: Optional[str], lead: Dict[str, Any],
    ) -> None:
        """שומר עותק של ההקלטה ב-recordings/ עם שם קריא."""
        try:
            rec_dir = Path(__file__).resolve().parent.parent / "recordings"
            rec_dir.mkdir(exist_ok=True)
            name = lead.get("fields", {}).get("שם", "").strip() or "ללא שם"
            date_str = ""
            if start_time:
                try:
                    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    date_str = dt.strftime("%d.%m.%Y")
                except Exception:
                    pass
            filename = f"{name} {date_str}.mp3".strip()
            dest = rec_dir / filename
            if not dest.exists():
                shutil.copy2(audio_path, dest)
                log.info("Recording saved: %s", dest.name)
        except Exception as e:
            log.warning("Failed to save recording copy: %s", e)

    def _record_has_transcript(self, record: Optional[Dict[str, Any]]) -> bool:
        """בודק אם לרשומה יש כבר תמלול (לפי field-id/שם שדה)."""
        if not record:
            return False
        fields = record.get("fields", {}) or {}
        transcript_candidates = [
            self.airtable.f("transcript"),
            "fldgOnnjDd3AV66GM",
            "תמלול שיחה",
            "Transcript",
            "transcript",
        ]
        for key in transcript_candidates:
            value = fields.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    def run(self) -> Dict[str, int]:
        stats = {"processed": 0, "skipped": 0, "errors": 0, "no_match": 0}
        lookback = self.config["pipeline"]["twilio_lookback_hours"]

        try:
            recordings = self.list_recordings(lookback)
            log.info("Twilio: found %d recordings in last %d hours", len(recordings), lookback)
        except Exception as e:
            log.exception("Twilio list_recordings failed: %s", e)
            stats["errors"] += 1
            return stats

        for rec in recordings:
            call_sid = rec.get("call_sid")
            rec_sid = rec.get("sid")
            if not call_sid or not rec_sid:
                continue

            # סינון הקלטות קצרות (פחות מ-3 דקות) — שיחה שלא באמת התקיימה
            try:
                rec_duration = float(rec.get("duration") or 0)
            except (TypeError, ValueError):
                rec_duration = 0.0
            if rec_duration and rec_duration < 180:
                log.info(
                    "Skipping short recording %s (%.0f sec < 180)",
                    rec_sid, rec_duration,
                )
                stats["skipped"] += 1
                continue

            # דילוג אם כבר עובד — call_sid קיים ויש תמלול
            existing = self.airtable.find_by_call_sid(call_sid)
            if existing:
                fields = existing.get("fields", {}) or {}
                has_transcript = any(
                    isinstance(fields.get(k), str) and fields.get(k, "").strip()
                    for k in ("תמלול השיחה", "תמלול שיחה", "Transcript", "transcript",
                              self.airtable.f("transcript"))
                )
                if has_transcript:
                    stats["skipped"] += 1
                    continue
                log.info("Record has call_sid but no transcript — will re-process: %s", call_sid)

            try:
                self._process_recording(rec, call_sid, rec_sid)
                stats["processed"] += 1
            except Exception as e:
                log.exception("Failed to process recording %s: %s", rec_sid, e)
                stats["errors"] += 1

        log.info("Twilio sync done: %s", stats)
        return stats

    def _process_recording(self, rec: Dict[str, Any], call_sid: str, rec_sid: str):
        """עיבוד הקלטה בודדת: מטא → תמלול → ניתוח → טיוטה → Airtable."""
        log.info("Processing recording %s (call %s)", rec_sid, call_sid)

        # שלב 1 — שליפת פרטי שיחה
        call = self.get_call(call_sid)
        from_num = normalize_phone(call.get("from", ""))
        to_num = normalize_phone(call.get("to", ""))
        mine = {
            normalize_phone(self.my_number),
            normalize_phone(self.my_personal_number),
        }
        if from_num and to_num and from_num == to_num and from_num in mine:
            log.info("agan_route_detected call_sid=%s from=%s to=%s", call_sid, from_num, to_num)
        lead_phone = self._get_lead_phone(call)
        duration_sec = float(call.get("duration") or rec.get("duration") or 0)
        duration_min = round(duration_sec / 60, 1)
        start_time = call.get("start_time") or rec.get("date_created")
        recording_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Recordings/{rec_sid}.mp3"
        )

        # אין מספר ליד אמין מהשיחה — לא מנחשים לפי חלון זמן כדי למנוע שיוך שגוי.
        if lead_phone is None:
            log.warning(
                "Skipping call %s — no lead phone extracted; time-window fallback disabled",
                call_sid,
            )
            return

        # שלב 2 — התאמה לליד קיים (שלוש שכבות: טלפון → חלון זמן → יצירת יתום)
        lead = self.airtable.find_by_phone(lead_phone)

        # שכבה 2ב — נסיון התאמה לפי חלון זמן סביב call_datetime (למקרה שהטלפון חסר/שונה)
        if not lead and start_time:
            try:
                matched = self.airtable.find_unclaimed_lead_near(start_time, hours=2)
                if matched:
                    log.info(
                        "Matched lead %s by time window (±2h) around %s",
                        matched.get("id"), start_time,
                    )
                    lead = matched
            except Exception as e:
                log.warning("find_unclaimed_lead_near failed: %s", e)

        if not lead:
            log.warning("No lead match for phone %s — creating new orphan record", lead_phone)
            created = self.airtable.create_record({
                self.airtable.f("name"): f"ליד ללא התאמה ({lead_phone})",
                self.airtable.f("phone"): lead_phone,
                self.airtable.f("status"): "חדש",
            })
            lead = {"id": created["id"], "fields": created["fields"]}

        # Append של Call SID (במקום דריסה) — תומך בכמה שיחות לאותו ליד
        existing_sid = lead.get("fields", {}).get("Twilio Call SID", "") or ""
        merged_sid = self.airtable.append_call_sid(existing_sid, call_sid)

        # אם הליד כבר היה מוזן ידנית עם טלפון אבל בלי טלפון ב-Twilio — נשלים
        update_fields = {
            self.airtable.f("twilio_call_sid"): merged_sid,
            self.airtable.f("recording_url"): recording_url,
            self.airtable.f("call_datetime"): start_time,
            self.airtable.f("call_duration_min"): duration_min,
        }
        if lead_phone and not lead.get("fields", {}).get("טלפון"):
            update_fields[self.airtable.f("phone")] = lead_phone

        # עדכון מיידי של מטא (לפני תמלול איטי) — למנוע reprocess
        self.airtable.update_record(lead["id"], update_fields)

        # הגנה על עלות תמלול: אם כבר קיים תמלול עבור Call SID — דילוג מלא על תמלול חוזר
        existing_for_sid = self.airtable.find_by_call_sid(call_sid)
        if self._record_has_transcript(existing_for_sid):
            log.info("skip_transcription_already_exists call_sid=%s", call_sid)
            return

        # שלב 3 — הורדה + שמירה מקומית + תמלול
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            audio_path = tmp.name
        try:
            self.download_recording(rec_sid, audio_path)
            log.info("Downloaded %.1f MB", os.path.getsize(audio_path) / 1024 / 1024)
            self._save_recording_copy(audio_path, call_sid, start_time, lead)
            transcript = self.transcriber.transcribe(audio_path)
        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        if not transcript:
            log.error("Empty transcript for %s", call_sid)
            self.airtable.update_record(lead["id"], {
                self.airtable.f("transcript"): "[תמלול נכשל]",
            })
            raise RuntimeError("Empty transcript")

        # שלב 4 — עדכון התמלול
        self.airtable.update_record(lead["id"], {
            self.airtable.f("transcript"): transcript,
            self.airtable.f("status"): "התקיימה שיחה",
        })
        log.info("Transcript saved (%d chars)", len(transcript))

        # שלב 5 — ניתוח AI
        lead_name = lead["fields"].get("שם", "")
        insights_dict, insights_json = self.analyzer.analyze(transcript, lead_name=lead_name)
        self.airtable.update_record(lead["id"], {
            self.airtable.f("ai_insights"): insights_json,
        })
        log.info("AI insights saved")

        # שלב 6 — טיוטת מייל ב-Gmail
        lead_email = lead["fields"].get("Email", "")
        if not lead_email:
            log.warning("No email for lead %s — skipping Gmail draft", lead["id"])
            self.airtable.update_record(lead["id"], {
                self.airtable.f("status"): "חסר מייל - ידני",
            })
            return

        script_dir = Path(__file__).resolve().parent.parent
        draft_result = self.email_drafter.create_draft(
            to_email=lead_email,
            lead_name=lead_name,
            insights=insights_dict,
            templates_dir=script_dir / self.config["paths"]["templates_dir"],
            logo_path=script_dir / self.config["paths"]["logo_path"],
            pdf_path=script_dir / self.config["paths"]["pdf_path"],
            transcript=transcript,
        )
        self.airtable.update_record(lead["id"], {
            self.airtable.f("gmail_draft_link"): draft_result["link"],
            self.airtable.f("status"): "טיוטה מוכנה",
        })
        log.info("Gmail draft created: %s", draft_result["link"])
