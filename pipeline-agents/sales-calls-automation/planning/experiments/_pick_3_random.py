"""סקריפט חד-פעמי: בוחר 3 הקלטות רנדומליות מ-Twilio לבדיקה."""
import os
import random
from pathlib import Path
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

sid = os.environ["TWILIO_ACCOUNT_SID"]
token = os.environ["TWILIO_AUTH_TOKEN"]
auth = HTTPBasicAuth(sid, token)
base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"

url = f"{base}/Recordings.json"
params = {"PageSize": 100}
recs = []
while url:
    r = requests.get(url, auth=auth, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    recs.extend(data.get("recordings", []))
    nxt = data.get("next_page_uri")
    url = f"https://api.twilio.com{nxt}" if nxt else None
    params = None

eligible = []
for r in recs:
    try:
        d = float(r.get("duration") or 0)
    except Exception:
        d = 0.0
    if d >= 30 and r.get("call_sid"):
        eligible.append({
            "call_sid": r["call_sid"],
            "rec_sid": r["sid"],
            "duration": d,
            "date": r.get("date_created"),
        })

print(f"TOTAL_RECORDINGS: {len(recs)}")
print(f"ELIGIBLE_30SEC+:  {len(eligible)}")

already = set()
sd = SCRIPT_DIR / "state" / "diarized"
if sd.exists():
    for p in sd.glob("*.json"):
        already.add(p.stem)
print(f"ALREADY_DONE:     {len(already)}")

remaining = [e for e in eligible if e["call_sid"] not in already]
print(f"REMAINING:        {len(remaining)}")

random.seed(42)
sample = random.sample(remaining, min(3, len(remaining))) if remaining else []
print("\n=== SELECTED 3 RANDOM CALLS ===")
for i, s in enumerate(sample, 1):
    mins = s["duration"] / 60
    print(f"  [{i}] {s['call_sid']} | {s['duration']:.0f}s ({mins:.1f}min) | {s['date']}")
print("\nSIDS=" + ",".join(s["call_sid"] for s in sample))
