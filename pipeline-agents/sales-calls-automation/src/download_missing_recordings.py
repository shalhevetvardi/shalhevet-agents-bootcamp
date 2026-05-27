#!/usr/bin/env python3
"""הורדת הקלטות חסרות מ-Twilio — רק שיחות שאין להן קובץ בתיקיית recordings/."""

import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = SCRIPT_DIR / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(SCRIPT_DIR))
from modules.airtable_client import AirtableClient

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
AUTH = HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN)
BASE_URL = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}"

AIRTABLE_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_TABLE = os.environ["AIRTABLE_TABLE_ID"]


def list_all_recordings():
    url = f"{BASE_URL}/Recordings.json"
    params = {"PageSize": 100}
    all_recs = []
    while url:
        r = requests.get(url, auth=AUTH, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        all_recs.extend(data.get("recordings", []))
        nxt = data.get("next_page_uri")
        url = f"https://api.twilio.com{nxt}" if nxt else None
        params = None
    return all_recs


def get_call(call_sid):
    r = requests.get(f"{BASE_URL}/Calls/{call_sid}.json", auth=AUTH, timeout=30)
    r.raise_for_status()
    return r.json()


def existing_call_sids():
    """Call SIDs that already exist as files (check old and new format)."""
    sids = set()
    for f in RECORDINGS_DIR.iterdir():
        if f.suffix in (".mp3", ".m4a"):
            name = f.stem
            for part in name.split("_"):
                if part.startswith("CA") and len(part) > 30:
                    sids.add(part)
    return sids


def build_lead_map():
    """Build call_sid → lead_name from Airtable."""
    headers = {"Authorization": f"Bearer {AIRTABLE_KEY}"}
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{AIRTABLE_TABLE}"
    records = []
    params = {"pageSize": 100}
    while True:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset

    sid_to_name = {}
    for rec in records:
        fields = rec.get("fields", {})
        name = fields.get("שם", "").strip()
        sid_raw = fields.get("Twilio Call SID", "") or ""
        for sid in sid_raw.split(","):
            sid = sid.strip()
            if sid.startswith("CA"):
                sid_to_name[sid] = name
    return sid_to_name


def main():
    print("Fetching recordings from Twilio...")
    recordings = list_all_recordings()
    print(f"  Found {len(recordings)} recordings total")

    print("Building lead map from Airtable...")
    lead_map = build_lead_map()
    print(f"  {len(lead_map)} call SIDs mapped to leads")

    already = existing_call_sids()
    print(f"  {len(already)} call SIDs already downloaded")

    to_download = []
    for rec in recordings:
        call_sid = rec.get("call_sid", "")
        duration = int(rec.get("duration") or 0)
        if not call_sid:
            continue
        if call_sid in already:
            continue
        if duration < 10:
            continue
        to_download.append(rec)

    print(f"\n{len(to_download)} recordings to download:\n")

    if not to_download:
        print("Nothing to download!")
        return

    for rec in to_download:
        call_sid = rec["call_sid"]
        rec_sid = rec["sid"]
        name = lead_map.get(call_sid, "")

        date_str = ""
        raw_date = rec.get("date_created", "")
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y")
            except Exception:
                pass

        if not name:
            try:
                call = get_call(call_sid)
                from_num = call.get("from", "")
                to_num = call.get("to", "")
                name = f"לא ידוע {to_num or from_num}"
            except Exception:
                name = "לא ידוע"

        filename = f"{name} {date_str}.mp3".strip()
        dest = RECORDINGS_DIR / filename

        if dest.exists():
            print(f"  SKIP (exists): {filename}")
            continue

        print(f"  Downloading: {filename} ...", end=" ", flush=True)
        try:
            mp3_url = f"{BASE_URL}/Recordings/{rec_sid}.mp3"
            r = requests.get(mp3_url, auth=AUTH, timeout=120, stream=True)
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            tmp.rename(dest)
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"OK ({size_mb:.1f} MB)")
        except Exception as e:
            print(f"FAILED: {e}")

    print("\nDone!")


if __name__ == "__main__":
    main()
