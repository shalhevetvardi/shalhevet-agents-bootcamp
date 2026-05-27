#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_transcript_match.py
===========================
וידוא שהתמלול בעמודת 'תמלול עם דוברים' שייך באמת לאותה שיחה
כמו התמלול המקורי (field_id מ-config.json) באותה רשומה.

האלגוריתם
---------
1. טוען field_id של התמלול המקורי מ-config.json (airtable.fields.transcript).
2. דרך Meta API מוצא את field_id של העמודה 'תמלול עם דוברים' (או שם אחר שניתן
   דרך --diarized-field).
3. שולף את כל הרשומות מ-Airtable עם returnFieldsByFieldId=true (כדי לא
   להיתקע על שמות תצוגה שונים).
4. לכל רשומה עם שני השדות מלאים:
   - מנקה את שני הטקסטים (הסרת תגי דוברים, פיסוק, lowercase).
   - מחשב Jaccard על מילים ייחודיות.
5. מסמן אי-התאמות מתחת לסף, ומציע "מקור חשוד" לכל מקרה.

הפעלה
-----
    python3 verify_transcript_match.py
    python3 verify_transcript_match.py --show-all
    python3 verify_transcript_match.py --threshold 0.2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"
REPORTS_DIR = SCRIPT_DIR / "state" / "verify_reports"
CONFIG_PATH = SCRIPT_DIR / "config.json"

DEFAULT_DIARIZED_FIELD_NAME = "תמלול עם דוברים"

# תגי דוברים להסרה לפני השוואה
SPEAKER_LABEL_PATTERNS = [
    re.compile(r"\[דובר\s*\d+\][:\s]*"),
    re.compile(r"דובר\s*\d+\s*:"),
    re.compile(r"\[SPEAKER[_\s]*\d+\][:\s]*", re.IGNORECASE),
    re.compile(r"SPEAKER[_\s]*\d+\s*:", re.IGNORECASE),
]
# שומר אותיות עברית + אנגלית + ספרות; מסיר פיסוק
PUNCTUATION_RE = re.compile(r"[^\w\u0590-\u05FF\s]", re.UNICODE)


# ============================================================
# לוגינג
# ============================================================

def setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOGS_DIR / "verify_transcript.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(sh)
    return root


# ============================================================
# Airtable
# ============================================================

def _headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def get_field_id_by_name(base_id: str, table_id: str, api_key: str,
                         field_name: str) -> Optional[str]:
    """מוצא field_id של שדה לפי שם תצוגה (דרך Meta API)."""
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    r = requests.get(url, headers=_headers(api_key), timeout=30)
    r.raise_for_status()
    for tbl in r.json().get("tables", []):
        if tbl.get("id") != table_id:
            continue
        for fld in tbl.get("fields", []):
            if fld.get("name") == field_name:
                return fld.get("id")
    return None


def get_field_name_by_id(base_id: str, table_id: str, api_key: str,
                         field_id: str) -> Optional[str]:
    """הופך field_id לשם תצוגה (לדוחות בלבד)."""
    url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    r = requests.get(url, headers=_headers(api_key), timeout=30)
    r.raise_for_status()
    for tbl in r.json().get("tables", []):
        if tbl.get("id") != table_id:
            continue
        for fld in tbl.get("fields", []):
            if fld.get("id") == field_id:
                return fld.get("name")
    return None


def list_all_records_by_id(base_id: str, table_id: str,
                           api_key: str) -> List[Dict[str, Any]]:
    """שולף את כל הרשומות עם returnFieldsByFieldId=true."""
    headers = _headers(api_key)
    url = f"https://api.airtable.com/v0/{base_id}/{table_id}"
    out: List[Dict[str, Any]] = []
    offset: Optional[str] = None
    while True:
        params: Dict[str, Any] = {"pageSize": 100, "returnFieldsByFieldId": "true"}
        if offset:
            params["offset"] = offset
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return out


# ============================================================
# עיבוד טקסט + Jaccard
# ============================================================

def normalize_text(text: str) -> List[str]:
    """מוציא מהטקסט את המילים בלבד — בלי תגי דוברים, בלי פיסוק, lowercase."""
    if not text:
        return []
    for pat in SPEAKER_LABEL_PATTERNS:
        text = pat.sub(" ", text)
    text = PUNCTUATION_RE.sub(" ", text.lower())
    return [w for w in text.split() if w]


def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ============================================================
# לוגיקה
# ============================================================

def _rec_name(rec: Dict[str, Any], name_field_id: Optional[str]) -> str:
    fields = rec.get("fields", {}) or {}
    if name_field_id and fields.get(name_field_id):
        return str(fields[name_field_id])
    return rec.get("id", "(unnamed)")


def find_best_origin(
    diar_words: List[str],
    records: List[Dict[str, Any]],
    original_fid: str,
    name_fid: Optional[str],
    exclude_rec_id: str,
) -> Optional[Tuple[str, str, float]]:
    """מחזיר (rec_id, name, score) של הרשומה שהתמלול המקורי שלה הכי דומה
    לתמלול-עם-הדוברים שנבדק."""
    best: Optional[Tuple[str, str, float]] = None
    for other in records:
        if other.get("id") == exclude_rec_id:
            continue
        orig = ((other.get("fields", {}) or {}).get(original_fid) or "").strip()
        if not orig or orig.startswith("[תמלול נכשל"):
            continue
        score = jaccard(diar_words, normalize_text(orig))
        if best is None or score > best[2]:
            best = (other.get("id"), _rec_name(other, name_fid), score)
    return best


def verify(
    records: List[Dict[str, Any]],
    original_fid: str,
    diarized_fid: str,
    name_fid: Optional[str],
    threshold: float,
    log: logging.Logger,
    show_all: bool,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "threshold": threshold,
        "total_records": len(records),
        "compared": 0,
        "missing_original": 0,
        "missing_diarized": 0,
        "missing_both": 0,
        "skipped_failed_original": 0,
        "match": 0,
        "mismatch": 0,
        "mismatches": [],
        "scores": [],
    }

    for rec in records:
        fields = rec.get("fields", {}) or {}
        rec_id = rec.get("id", "")
        name = _rec_name(rec, name_fid)
        orig = (fields.get(original_fid) or "").strip()
        diar = (fields.get(diarized_fid) or "").strip()

        if not orig and not diar:
            out["missing_both"] += 1
            continue
        if not orig:
            out["missing_original"] += 1
            continue
        if not diar:
            out["missing_diarized"] += 1
            continue
        if orig.startswith("[תמלול נכשל"):
            out["skipped_failed_original"] += 1
            continue

        a = normalize_text(orig)
        b = normalize_text(diar)
        score = round(jaccard(a, b), 3)
        out["compared"] += 1

        entry: Dict[str, Any] = {
            "record_id": rec_id,
            "name": name,
            "score": score,
            "orig_words": len(a),
            "diar_words": len(b),
        }

        if score >= threshold:
            out["match"] += 1
            if show_all:
                log.info("✓ %s — score=%.3f (orig=%d / diar=%d words)",
                         name, score, len(a), len(b))
            out["scores"].append(entry)
        else:
            out["mismatch"] += 1
            log.warning(
                "✗ MISMATCH — %s (%s) — score=%.3f (orig=%d / diar=%d words)",
                name, rec_id, score, len(a), len(b),
            )
            suspected = find_best_origin(b, records, original_fid, name_fid, rec_id)
            if suspected:
                sug_id, sug_name, sug_score = suspected
                log.warning(
                    "    ⇒ מקור חשוד: %s (%s) — score=%.3f",
                    sug_name, sug_id, sug_score,
                )
            entry.update({
                "orig_preview": orig[:250],
                "diar_preview": diar[:250],
                "suspected_source": (
                    {
                        "record_id": suspected[0],
                        "name": suspected[1],
                        "score": round(suspected[2], 3),
                    }
                    if suspected else None
                ),
            })
            out["mismatches"].append(entry)
            out["scores"].append(entry)

    out["mismatches"].sort(key=lambda x: x["score"])
    out["scores"].sort(key=lambda x: x["score"])
    return out


# ============================================================
# דוח
# ============================================================

def save_report(results: Dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"verify_report_{ts}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return path


def print_summary(results: Dict[str, Any], original_name: str,
                  diarized_name: str) -> None:
    th = results["threshold"]
    print("\n" + "=" * 72)
    print(f" דוח וידוא תמלולים — '{original_name}' ↔ '{diarized_name}'")
    print("=" * 72)
    print(f" סף Jaccard:                          {th}")
    print(f" סה״כ רשומות:                         {results['total_records']}")
    print(f" הושוו (ערך בשתי העמודות):            {results['compared']}")
    print(f" חסר תמלול מקורי בלבד:                {results['missing_original']}")
    print(f" חסר תמלול עם דוברים בלבד:            {results['missing_diarized']}")
    print(f" חסרים שניהם:                         {results['missing_both']}")
    print(f" דילגו על '[תמלול נכשל]':              {results['skipped_failed_original']}")
    print(f" ✓ התאמה:                              {results['match']}")
    print(f" ✗ אי-התאמה (חשד לעמודה לא נכונה):    {results['mismatch']}")
    print("=" * 72)

    if results["mismatches"]:
        print("\nרשימת אי-התאמות (מהגרוע ביותר):")
        for m in results["mismatches"]:
            print(f"\n  • {m['name']}  ({m['record_id']})")
            print(
                f"    Jaccard: {m['score']}  |  מילים: מקורי={m['orig_words']}, "
                f"דוברים={m['diar_words']}"
            )
            if m.get("suspected_source"):
                s = m["suspected_source"]
                print(
                    f"    חשד למקור הנכון:  {s['name']}  ({s['record_id']})  "
                    f"— score={s['score']}"
                )
            print(f"    תמלול מקורי (פתיח):  {m['orig_preview'][:180]}…")
            print(f"    תמלול דוברים (פתיח): {m['diar_preview'][:180]}…")
    print()


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="מזהה אי-התאמות בין עמודת 'תמלול עם דוברים' לעמודת התמלול המקורית",
    )
    p.add_argument(
        "--threshold", type=float, default=0.3,
        help="סף Jaccard מתחתיו הרשומה מסומנת כאי-התאמה (ברירת מחדל: 0.3)",
    )
    p.add_argument(
        "--show-all", action="store_true",
        help="הדפס גם ציונים של רשומות תקינות",
    )
    p.add_argument(
        "--diarized-field", type=str, default=DEFAULT_DIARIZED_FIELD_NAME,
        help=f"שם עמודת הדיאריזציה (ברירת מחדל: {DEFAULT_DIARIZED_FIELD_NAME})",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    log = setup_logging()
    load_dotenv(SCRIPT_DIR / ".env")

    required = ["AIRTABLE_API_KEY", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE_ID"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        return 2

    base_id = os.environ["AIRTABLE_BASE_ID"]
    table_id = os.environ["AIRTABLE_TABLE_ID"]
    api_key = os.environ["AIRTABLE_API_KEY"]

    # 1. field IDs מ-config.json
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    original_fid = cfg["airtable"]["fields"]["transcript"]
    name_fid = cfg["airtable"]["fields"].get("name")
    log.info("Original transcript field_id: %s", original_fid)

    # 2. Meta API — שם תצוגה של התמלול המקורי + field_id של הדיאריזציה
    original_name = get_field_name_by_id(base_id, table_id, api_key, original_fid)
    if not original_name:
        log.warning("Could not resolve display name for %s — using ID", original_fid)
        original_name = original_fid
    log.info("Original transcript display name: %s", original_name)

    diarized_fid = get_field_id_by_name(base_id, table_id, api_key, args.diarized_field)
    if not diarized_fid:
        log.error("Field '%s' not found in table %s. נסי --diarized-field עם השם המדויק.",
                  args.diarized_field, table_id)
        return 3
    log.info("Diarized field '%s' → field_id: %s", args.diarized_field, diarized_fid)

    # 3. שליפת רשומות לפי field IDs
    log.info("Fetching records…")
    records = list_all_records_by_id(base_id, table_id, api_key)
    log.info("Fetched %d records", len(records))

    # 4. השוואה
    results = verify(
        records=records,
        original_fid=original_fid,
        diarized_fid=diarized_fid,
        name_fid=name_fid,
        threshold=args.threshold,
        log=log,
        show_all=args.show_all,
    )
    results["original_field"] = {"id": original_fid, "name": original_name}
    results["diarized_field"] = {"id": diarized_fid, "name": args.diarized_field}

    report = save_report(results)
    log.info("Saved report → %s", report)

    print_summary(results, original_name, args.diarized_field)
    return 0 if results["mismatch"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
