#!/usr/bin/env python3
"""
Fetch details of 2 unmatched calls from Twilio and download their recordings.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]

CALLS = [
    "CA66f3783b2fcae582310f6f99d878b7f2",
    "CA0646ef03e835b94d72ab6859be18124c",
]

RECORDINGS = [
    "RE35f5c3491271912cb3aa68eea0458d55",
    "RE5a8dc37827e0938b86630933b90e4e48",
]

BASE = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}"
AUTH = (ACCOUNT_SID, AUTH_TOKEN)

for sid in CALLS:
    url = f"{BASE}/Calls/{sid}.json"
    r = requests.get(url, auth=AUTH, timeout=15)
    r.raise_for_status()
    data = r.json()
    print(f"\n=== Call {sid} ===")
    print(f"  From:      {data.get('from_formatted', data.get('from'))}")
    print(f"  To:        {data.get('to_formatted', data.get('to'))}")
    print(f"  Status:    {data.get('status')}")
    print(f"  Start:     {data.get('start_time')}")
    print(f"  End:       {data.get('end_time')}")
    print(f"  Duration:  {data.get('duration')}s")
    print(f"  Direction: {data.get('direction')}")

os.makedirs("/tmp/unmatched_calls", exist_ok=True)

for rec_sid in RECORDINGS:
    url = f"{BASE}/Recordings/{rec_sid}.mp3"
    print(f"\nDownloading {rec_sid}...")
    r = requests.get(url, auth=AUTH, timeout=120, stream=True)
    r.raise_for_status()
    path = f"/tmp/unmatched_calls/{rec_sid}.mp3"
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"  Saved: {path} ({size_mb:.1f} MB)")

print("\nDone.")
