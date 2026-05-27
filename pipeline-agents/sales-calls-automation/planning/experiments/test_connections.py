#!/usr/bin/env python3
"""
test_connections.py — בדיקת כל החיבורים החיצוניים לפני ההרצה הראשונה.
מריץ פינג לכל שירות ומדווח מה עובד.
הרצה: python3 test_connections.py
"""
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

OK = "\033[92m✓\033[0m"
BAD = "\033[91m✗\033[0m"


def test_airtable():
    import requests
    try:
        r = requests.get(
            f"https://api.airtable.com/v0/{os.environ['AIRTABLE_BASE_ID']}/{os.environ['AIRTABLE_TABLE_ID']}",
            headers={"Authorization": f"Bearer {os.environ['AIRTABLE_API_KEY']}"},
            params={"maxRecords": 1},
            timeout=15,
        )
        r.raise_for_status()
        return True, f"{len(r.json().get('records', []))} records reachable"
    except Exception as e:
        return False, str(e)[:120]


def test_twilio():
    import requests
    from requests.auth import HTTPBasicAuth
    try:
        r = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{os.environ['TWILIO_ACCOUNT_SID']}.json",
            auth=HTTPBasicAuth(
                os.environ["TWILIO_ACCOUNT_SID"],
                os.environ["TWILIO_AUTH_TOKEN"],
            ),
            timeout=15,
        )
        r.raise_for_status()
        return True, f"Account: {r.json().get('friendly_name', 'OK')}"
    except Exception as e:
        return False, str(e)[:120]


def test_calendly():
    import requests
    try:
        r = requests.get(
            "https://api.calendly.com/users/me",
            headers={"Authorization": f"Bearer {os.environ['CALENDLY_API_TOKEN']}"},
            timeout=15,
        )
        r.raise_for_status()
        user = r.json().get("resource", {})
        return True, f"User: {user.get('name')} <{user.get('email')}>"
    except Exception as e:
        return False, str(e)[:120]


def test_anthropic():
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "say OK"}],
        )
        return True, resp.content[0].text[:50]
    except Exception as e:
        return False, str(e)[:120]


def test_runpod():
    import requests
    endpoint_id = os.environ["RUNPOD_ENDPOINT_ID"]
    api_key = os.environ["RUNPOD_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}"}
    # נסה כמה URLים — RunPod לפעמים דורש serverless path אחר
    urls_to_try = [
        f"https://api.runpod.ai/v2/{endpoint_id}/health",
        f"https://api.runpod.ai/v2/{endpoint_id}/status",
        f"https://api.runpod.ai/graphql",
    ]
    last_error = None
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code < 400:
                return True, f"endpoint reachable ({url.split('/')[-1]})"
            last_error = f"{r.status_code} at {url.split('/')[-1]}"
        except Exception as e:
            last_error = str(e)[:80]
    # נסה POST עם query graphql שבודק שהמפתח תקין
    try:
        r = requests.post(
            "https://api.runpod.ai/graphql",
            headers={**headers, "Content-Type": "application/json"},
            json={"query": "{ myself { id email } }"},
            timeout=10,
        )
        if r.status_code == 200 and "errors" not in r.json():
            user = r.json().get("data", {}).get("myself", {})
            return True, f"API key valid (user: {user.get('email', 'ok')})"
    except Exception as e:
        last_error = str(e)[:80]
    return False, f"endpoint unreachable — check RUNPOD_ENDPOINT_ID ({last_error})"


def test_gmail():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            scopes=["https://www.googleapis.com/auth/gmail.compose"],
        )
        creds.refresh(Request())
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return True, f"Gmail: {profile.get('emailAddress')}"
    except Exception as e:
        return False, str(e)[:120]


def test_ffmpeg():
    import subprocess
    try:
        subprocess.check_output(["ffmpeg", "-version"], timeout=5)
        subprocess.check_output(["ffprobe", "-version"], timeout=5)
        return True, "ffmpeg + ffprobe available"
    except Exception as e:
        return False, f"install with: brew install ffmpeg ({e})"


def main():
    tests = [
        ("ffmpeg", test_ffmpeg),
        ("Airtable", test_airtable),
        ("Twilio", test_twilio),
        ("Calendly", test_calendly),
        ("Anthropic (Claude)", test_anthropic),
        ("RunPod (ivrit.ai)", test_runpod),
        ("Gmail", test_gmail),
    ]
    print("=" * 60)
    print("  בדיקת חיבורים")
    print("=" * 60)
    results = []
    for name, fn in tests:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, str(e)[:120]
        icon = OK if ok else BAD
        print(f"  {icon} {name:20s} {msg}")
        results.append(ok)
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"  {passed}/{total} passed")
    if passed == total:
        print("  הכל מוכן — אפשר להריץ את sales_pipeline.py")
    else:
        print("  יש מה לתקן לפני שמריצים את הפייפליין")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
