#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_diarized_to_airtable.py
===============================
סקריפט נפרד להעלאת תמלולי דיאריזציה (שלב 3 בפרויקט).

מה הוא עושה
-----------
1. טוען את .env ו-config.json מאותה תיקייה (קריאה בלבד).
2. בודק אם קיימת בטבלת Airtable עמודה בשם "תמלול עם דוברים".
   - אם קיימת: משתמש ב-field_id שלה.
   - אם לא קיימת: יוצר אותה דרך Meta API (type=multilineText).
3. סורק את state/diarized/*.json (פלט של transcribe_with_diarization.py).
4. מושך את כל רשומות Airtable פעם אחת (pagination).
5. לכל קובץ JSON:
   - מחלץ call_sid ו-formatted_text.
   - מחפש רשומה תואמת לפי substring match ב-Twilio Call SID.
   - מעדכן רק את העמודה החדשה (לא נוגע בעמודת התמלול הישנה).
6. מדפיס ושומר דוח סיכום.

מה הוא *לא* עושה
----------------
- לא נוגע בעמודות קיימות (לא בתמלול הישן, לא בשום עמודה אחרת).
- לא משנה את config.json.
- לא מוחק רשומות ולא משנה שדות אחרים.

הפעלה
-----
    # בדיקה בלי כתיבה (דמה בלבד):
    python3 upload_diarized_to_airtable.py --dry-run

    # הרצה רק על 3 שיחות ספציפיות (שלב 4):
    python3 upload_diarized_to_airtable.py --only-call-sids CAaaa,CAbbb,CAccc

    # דריסה של ערכים קיימים בעמודה החדשה:
    python3 upload_diarized_to_airtable.py --force

    # העלאה מלאה:
    python3 upload_diarized_to_airtable.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR = SCRIPT_DIR / "state" / "diarized"
LOGS_DIR = SCRIPT_DIR / "logs"
REPORTS_DIR = SCRIPT_DIR / "state" / "upload_reports"

NEW_FIELD_NAME = "תמלול עם דוברים"
NEW_FIELD_TYPE = "multilineText"
EXISTING_CALL_SID_COL_NAME = "Twilio Call SID"


# ============================================================
# לוגינג
# ============================================================

def setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "upload_diarized.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return root


# ============================================================
# Airtable — client ייעודי (לא נוגע במודול הקיים)
# ============================================================

@dataclass
class AirtableCfg:
    api_key: str
    base_id: str
    table_id: str

    @property
    def meta_fields_url(self) -> str:
        return (
            f"https://api.airtable.com/v0/meta/bases/{self.base_id}"
            f"/tables/{self.table_id}/fields"
        )

    @property
    def meta_tables_url(self) -> str:
        return f"https://api.airtable.com/v0/meta/bases/{self.base_id}/tables"

    @property
    def records_url(self) -> str:
        return f"https://api.airtable.com/v0/{self.base_id}/{self.table_id}"

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class AirtableUploader:
    def __init__(self, cfg: AirtableCfg):
        self.cfg = cfg
        self.log = logging.getLogger(__name__)

    # ---------- Meta API ----------

    def get_existing_field_id(self, field_name: str) -> Optional[str]:
        """בודק אם קיים שדה בשם זה בטבלה. מחזיר field_id או None."""
        r = requests.get(self.cfg.meta_tables_url, headers=self.cfg.headers, timeout=30)
        r.raise_for_status()
        tables = r.json().get("tables", [])
        for tbl in tables:
            if tbl.get("id") != self.cfg.table_id:
                continue
            for fld in tbl.get("fields", []):
                if fld.get("name") == field_name:
                    return fld.get("id")
        return None

    def create_field(self, name: str, field_type: str) -> str:
        """יוצר שדה חדש דרך Meta API. מחזיר את ה-field_id."""
        payload = {"name": name, "type": field_type}
        r = requests.post(
            self.cfg.meta_fields_url,
            headers=self.cfg.headers,
            json=payload,
            timeout=30,
        )
        if r.status_code >= 400:
            self.log.error("Field creation failed: %s %s", r.status_code, r.text)
        r.raise_for_status()
        data = r.json()
        fid = data.get("id")
        if not fid:
            raise RuntimeError(f"Field created but no id returned: {data}")
        return fid

    def ensure_field(self, name: str, field_type: str) -> str:
        """מחזיר field_id של שדה קיים או יוצר חדש."""
        existing = self.get_existing_field_id(name)
        if existing:
            self.log.info("Field '%s' already exists — id=%s", name, existing)
            return existing
        self.log.info("Field '%s' not found — creating (type=%s)", name, field_type)
        fid = self.create_field(name, field_type)
        self.log.info("Field '%s' created — id=%s", name, fid)
        return fid

    # ---------- Records API ----------

    def list_all_records(self) -> List[Dict[str, Any]]:
        """שולף את כל הרשומות (pagination). מחזיר עם display names (לא field IDs)."""
        records: List[Dict[str, Any]] = []
        offset: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            r = requests.get(
                self.cfg.records_url,
                headers=self.cfg.headers,
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return records

    def update_record(self, record_id: str, field_id: str, value: str) -> Dict[str, Any]:
        """מעדכן שדה יחיד לפי field_id. לא נוגע בשאר השדות."""
        url = f"{self.cfg.records_url}/{record_id}"
        payload = {"fields": {field_id: value}, "typecast": True}
        r = requests.patch(url, headers=self.cfg.headers, json=payload, timeout=30)
        if r.status_code >= 400:
            self.log.error("Update failed for %s: %s %s", record_id, r.status_code, r.text)
        r.raise_for_status()
        return r.json()


# ============================================================
# התאמת call_sid → record
# ============================================================

def find_record_by_sid(
    records: List[Dict[str, Any]],
    call_sid: str,
    sid_col_name: str = EXISTING_CALL_SID_COL_NAME,
) -> Optional[Dict[str, Any]]:
    """חיפוש רשומה שה-Call SID שלה (או רשימת SIDs) מכילה את ה-sid המבוקש."""
    if not call_sid:
        return None
    for rec in records:
        stored = rec.get("fields", {}).get(sid_col_name, "") or ""
        if call_sid in stored:
            return rec
    return None


# ============================================================
# עבודה עם JSON של דיאריזציה
# ============================================================

@dataclass
class DiarizedFile:
    path: Path
    call_sid: str
    formatted_text: str
    num_segments: int
    raw: Dict[str, Any]


def load_diarized_files(state_dir: Path) -> List[DiarizedFile]:
    """טוען את כל קבצי ה-JSON מ-state/diarized/.
    כל קובץ חייב להכיל: call_sid, formatted_text."""
    out: List[DiarizedFile] = []
    if not state_dir.exists():
        return out
    for p in sorted(state_dir.glob("*.json")):
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.warning("Skipping unreadable JSON: %s (%s)", p.name, e)
            continue
        call_sid = (data.get("call_sid") or "").strip()
        formatted_text = data.get("formatted_text") or ""
        segments = data.get("segments") or []
        if not call_sid:
            logging.warning("Skipping %s — no call_sid in JSON", p.name)
            continue
        if not formatted_text.strip():
            logging.warning("Skipping %s — empty formatted_text", p.name)
            continue
        out.append(
            DiarizedFile(
                path=p,
                call_sid=call_sid,
                formatted_text=formatted_text,
                num_segments=len(segments) if isinstance(segments, list) else 0,
                raw=data,
            )
        )
    return out


# ============================================================
# Orchestrator
# ============================================================

@dataclass
class Stats:
    total_files: int = 0
    updated: int = 0
    not_found: int = 0
    skipped_has_value: int = 0
    skipped_filter: int = 0
    failed: int = 0
    dry_run_would_update: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "updated": self.updated,
            "not_found": self.not_found,
            "skipped_has_value": self.skipped_has_value,
            "skipped_filter": self.skipped_filter,
            "failed": self.failed,
            "dry_run_would_update": self.dry_run_would_update,
            "details": self.details,
        }


def run(
    cfg: AirtableCfg,
    state_dir: Path,
    field_name: str,
    field_type: str,
    only_call_sids: Optional[List[str]],
    dry_run: bool,
    force: bool,
    sleep_between: float,
) -> Stats:
    log = logging.getLogger(__name__)
    uploader = AirtableUploader(cfg)

    # 1. טעינת קבצי JSON
    files = load_diarized_files(state_dir)
    log.info("Loaded %d diarized JSON files from %s", len(files), state_dir)

    if only_call_sids:
        allow = set(s.strip() for s in only_call_sids if s.strip())
        before = len(files)
        files_filtered = [f for f in files if f.call_sid in allow]
        log.info("Filter --only-call-sids: %d/%d match", len(files_filtered), before)
        filter_skipped = before - len(files_filtered)
        files = files_filtered
    else:
        filter_skipped = 0

    stats = Stats(total_files=len(files), skipped_filter=filter_skipped)

    if not files:
        log.warning("No files to process — exiting")
        return stats

    # 2. ודא שהשדה קיים (או צור אותו)
    if dry_run:
        existing = uploader.get_existing_field_id(field_name)
        if existing:
            field_id = existing
            log.info("[DRY-RUN] Field '%s' exists — id=%s", field_name, field_id)
        else:
            field_id = "<WOULD-CREATE-NEW-FIELD>"
            log.info("[DRY-RUN] Field '%s' would be created (type=%s)", field_name, field_type)
    else:
        field_id = uploader.ensure_field(field_name, field_type)

    # 3. שלוף את כל הרשומות פעם אחת
    log.info("Fetching all Airtable records…")
    records = uploader.list_all_records()
    log.info("Fetched %d records", len(records))

    # 4. עבוד קובץ-אחר-קובץ
    for i, df in enumerate(files, start=1):
        prefix = f"[{i}/{len(files)}] call_sid={df.call_sid}"
        rec = find_record_by_sid(records, df.call_sid)
        if not rec:
            log.warning("%s — no matching Airtable record", prefix)
            stats.not_found += 1
            stats.details.append({
                "call_sid": df.call_sid,
                "file": df.path.name,
                "status": "not_found",
            })
            continue

        rec_id = rec["id"]
        rec_name = rec.get("fields", {}).get("שם", "")
        existing_value = (rec.get("fields", {}).get(field_name) or "").strip()

        if existing_value and not force and not dry_run:
            log.info("%s — target field already has value for '%s' (%s), skipping",
                     prefix, rec_name, rec_id)
            stats.skipped_has_value += 1
            stats.details.append({
                "call_sid": df.call_sid,
                "file": df.path.name,
                "record_id": rec_id,
                "name": rec_name,
                "status": "skipped_has_value",
            })
            continue

        if dry_run:
            preview = df.formatted_text[:120].replace("\n", " ⏎ ")
            log.info("%s — [DRY-RUN] would update record %s (%s) — %d segments — preview: %s…",
                     prefix, rec_id, rec_name, df.num_segments, preview)
            stats.dry_run_would_update += 1
            stats.details.append({
                "call_sid": df.call_sid,
                "file": df.path.name,
                "record_id": rec_id,
                "name": rec_name,
                "status": "dry_run_would_update",
                "num_segments": df.num_segments,
            })
            continue

        try:
            uploader.update_record(rec_id, field_id, df.formatted_text)
            log.info("%s — ✓ updated record %s (%s), %d segments, %d chars",
                     prefix, rec_id, rec_name, df.num_segments, len(df.formatted_text))
            stats.updated += 1
            stats.details.append({
                "call_sid": df.call_sid,
                "file": df.path.name,
                "record_id": rec_id,
                "name": rec_name,
                "status": "updated",
                "num_segments": df.num_segments,
                "chars": len(df.formatted_text),
            })
        except Exception as e:
            log.exception("%s — update failed: %s", prefix, e)
            stats.failed += 1
            stats.details.append({
                "call_sid": df.call_sid,
                "file": df.path.name,
                "record_id": rec_id,
                "name": rec_name,
                "status": "failed",
                "error": str(e),
            })

        if sleep_between > 0:
            time.sleep(sleep_between)

    return stats


# ============================================================
# דוח
# ============================================================

def save_report(stats: Stats, dry_run: bool) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = "_DRYRUN" if dry_run else ""
    out = REPORTS_DIR / f"upload_report_{ts}{suffix}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(stats.as_dict(), f, ensure_ascii=False, indent=2)
    return out


def print_summary(stats: Stats, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "LIVE"
    print("\n" + "=" * 60)
    print(f" דוח סיכום — {mode}")
    print("=" * 60)
    print(f" סה״כ קבצי JSON לעיבוד:        {stats.total_files}")
    print(f" סוננו ע״י --only-call-sids:   {stats.skipped_filter}")
    if dry_run:
        print(f" היו מתעדכנים (dry-run):       {stats.dry_run_would_update}")
    else:
        print(f" עודכנו בהצלחה:                {stats.updated}")
    print(f" דילוג — כבר יש ערך בעמודה:    {stats.skipped_has_value}")
    print(f" לא נמצאה רשומה תואמת:         {stats.not_found}")
    print(f" נכשלו:                         {stats.failed}")
    print("=" * 60 + "\n")


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="העלאת תמלולי דיאריזציה לעמודה חדשה ב-Airtable",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="הדמיה בלבד — לא יוצר שדה, לא מעדכן רשומות",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="דריסה גם אם כבר יש ערך בעמודה החדשה",
    )
    p.add_argument(
        "--only-call-sids",
        type=str,
        default="",
        help="רשימת SIDs מופרדת בפסיקים — מעבד רק אותם",
    )
    p.add_argument(
        "--field-name",
        type=str,
        default=NEW_FIELD_NAME,
        help=f"שם העמודה החדשה (ברירת מחדל: {NEW_FIELD_NAME})",
    )
    p.add_argument(
        "--field-type",
        type=str,
        default=NEW_FIELD_TYPE,
        choices=["multilineText", "richText", "singleLineText"],
        help=f"סוג העמודה אם נוצרת (ברירת מחדל: {NEW_FIELD_TYPE})",
    )
    p.add_argument(
        "--state-dir",
        type=str,
        default=str(STATE_DIR),
        help=f"תיקיית JSON של דיאריזציה (ברירת מחדל: {STATE_DIR})",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="שינה בין בקשות (שניות) — להתחשב ב-rate limit של Airtable",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging()
    log = logging.getLogger(__name__)

    load_dotenv(SCRIPT_DIR / ".env")

    required = ["AIRTABLE_API_KEY", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return 2

    cfg = AirtableCfg(
        api_key=os.environ["AIRTABLE_API_KEY"],
        base_id=os.environ["AIRTABLE_BASE_ID"],
        table_id=os.environ["AIRTABLE_TABLE_ID"],
    )

    only_sids: Optional[List[str]] = None
    if args.only_call_sids.strip():
        only_sids = [s.strip() for s in args.only_call_sids.split(",") if s.strip()]

    log.info("=" * 60)
    log.info("upload_diarized_to_airtable — starting")
    log.info("  dry_run      = %s", args.dry_run)
    log.info("  force        = %s", args.force)
    log.info("  field_name   = %s", args.field_name)
    log.info("  field_type   = %s", args.field_type)
    log.info("  state_dir    = %s", args.state_dir)
    log.info("  only_sids    = %s", only_sids or "(all)")
    log.info("=" * 60)

    try:
        stats = run(
            cfg=cfg,
            state_dir=Path(args.state_dir),
            field_name=args.field_name,
            field_type=args.field_type,
            only_call_sids=only_sids,
            dry_run=args.dry_run,
            force=args.force,
            sleep_between=args.sleep,
        )
    except Exception as e:
        log.exception("Fatal error: %s", e)
        return 1

    report_path = save_report(stats, args.dry_run)
    log.info("Saved report → %s", report_path)
    print_summary(stats, args.dry_run)

    # קוד יציאה: 0 אם לא היו כשלים, 1 אחרת
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
