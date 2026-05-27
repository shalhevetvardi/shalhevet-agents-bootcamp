#!/usr/bin/env python3
"""Regenerate email drafts for 5 leads from April 24 (all except שלומי ez@ez-roi.com)."""

import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

sys.path.insert(0, os.path.dirname(__file__))

API_KEY = os.environ["AIRTABLE_API_KEY"]
BASE_ID = os.environ["AIRTABLE_BASE_ID"]
TABLE_ID = os.environ["AIRTABLE_TABLE_ID"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

DRAFT_LINK_FIELD = "fldM7XTuIL01wYQWp"

SCRIPT_DIR = Path(__file__).parent
with open(SCRIPT_DIR / "config.json") as f:
    config = json.load(f)

LEADS = [
    {"id": "recsF79hGA8v3Lr2s", "name": "ניר פלה", "email": "nirf66@gmail.com"},
    {"id": "recVEq3VnP8p1fjKC", "name": "איליה מייקלר", "email": "iliameykler@gmail.com"},
    {"id": "recVw9lNR3OnC5Zo0", "name": "טל שחר לוצאטו", "email": "tal.tric@gmail.com"},
    {"id": "rec0m7LUyTCJx5kyu", "name": "עדן עמר", "email": "edenkevon@gmail.com"},
    {"id": "recpNM1rJdboNZcnH", "name": "עדי מרגלית", "email": "adimargalit@gmail.com"},
]

from modules.analyze import EmailComposer
from modules.email_draft import GmailDraftCreator

composer = EmailComposer(
    api_key=os.environ["ANTHROPIC_API_KEY"],
    model=config["claude"]["model"],
    prompts_dir=str(SCRIPT_DIR / "prompts"),
    max_tokens=config["claude"]["max_tokens_email"],
)

email_drafter = GmailDraftCreator(
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    composer=composer,
)

templates_dir = SCRIPT_DIR / config["paths"]["templates_dir"]
logo_path = SCRIPT_DIR / config["paths"]["logo_path"]
pdf_path = SCRIPT_DIR / config["paths"]["pdf_path"]


def airtable_get(record_id):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}/{record_id}"
    r = requests.get(url, headers=HEADERS, params={"returnFieldsByFieldId": "true"}, timeout=15)
    r.raise_for_status()
    return r.json().get("fields", {})


def airtable_update(record_id, fields):
    url = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}/{record_id}"
    r = requests.patch(url, headers=HEADERS, json={"fields": fields}, timeout=30)
    if not r.ok:
        print(f"  ERROR {r.status_code}: {r.text}")
    r.raise_for_status()


TRANSCRIPT_FIELD = "fldgOnnjDd3AV66GM"
INSIGHTS_FIELD = "fldHOnZotRCU9qHpr"


def main():
    print(f"Regenerating email drafts for {len(LEADS)} leads...\n")

    success = 0
    for lead in LEADS:
        print(f"{'='*60}")
        print(f"  {lead['name']} ({lead['email']})")
        print(f"  Record: {lead['id']}")

        data = airtable_get(lead["id"])
        transcript = data.get(TRANSCRIPT_FIELD, "")
        insights_json = data.get(INSIGHTS_FIELD, "{}")

        if not transcript:
            print("  ⚠️  No transcript — skipping")
            continue

        try:
            insights = json.loads(insights_json)
        except json.JSONDecodeError:
            print("  ⚠️  Invalid insights JSON — skipping")
            continue

        print(f"  Transcript: {len(transcript)} chars")
        print(f"  Creating draft...")

        try:
            draft_result = email_drafter.create_draft(
                to_email=lead["email"],
                lead_name=lead["name"].split()[0],
                insights=insights,
                templates_dir=templates_dir,
                logo_path=logo_path,
                pdf_path=pdf_path,
                transcript=transcript,
            )

            print(f"  ✅ Draft: {draft_result['link']}")
            print(f"     Subject: {draft_result['subject']}")

            airtable_update(lead["id"], {DRAFT_LINK_FIELD: draft_result["link"]})
            print(f"  ✅ Airtable updated")
            success += 1

        except Exception as e:
            print(f"  ❌ FAILED: {e}")

        print()

    print(f"\n{'='*60}")
    print(f"Done: {success}/{len(LEADS)} drafts created.")
    return 0 if success == len(LEADS) else 1


if __name__ == "__main__":
    sys.exit(main())
