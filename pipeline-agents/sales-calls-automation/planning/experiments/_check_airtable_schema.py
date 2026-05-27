#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_check_airtable_schema.py — סקריפט בדיקה.

מציג:
    1. כל הטבלאות בבסיס (כדי לוודא איזה Table ID נכון)
    2. כל שמות השדות בטבלה הנוכחית (כדי לראות את השם המדויק של "תמלול שיחה")

הרצה:
    python3 _check_airtable_schema.py
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

api_key = os.getenv("AIRTABLE_API_KEY")
base_id = os.getenv("AIRTABLE_BASE_ID")
current_table_id = os.getenv("AIRTABLE_TABLE_ID")

if not (api_key and base_id):
    print("❌ חסר AIRTABLE_API_KEY או AIRTABLE_BASE_ID ב-.env")
    sys.exit(1)

resp = requests.get(
    f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
    headers={"Authorization": f"Bearer {api_key}"},
)
if resp.status_code >= 400:
    print(f"❌ שגיאת Airtable ({resp.status_code}): {resp.text}")
    sys.exit(1)

tables = resp.json().get("tables", [])

print("=" * 70)
print(f"בסיס: {base_id}")
print(f"AIRTABLE_TABLE_ID ב-.env: {current_table_id}")
print("=" * 70)

print("\n📋 כל הטבלאות בבסיס:\n")
for t in tables:
    marker = "  👉 " if t["id"] == current_table_id else "     "
    print(f"{marker}{t['name']:<30} | {t['id']} | {len(t['fields'])} שדות")

# מציג את השדות בטבלה הנוכחית
current_table = next((t for t in tables if t["id"] == current_table_id), None)
if not current_table:
    print(f"\n❌ הטבלה {current_table_id} לא נמצאה בבסיס. עדכני AIRTABLE_TABLE_ID ב-.env.")
    sys.exit(1)

print(f"\n📑 שדות בטבלה '{current_table['name']}':\n")
for f in current_table["fields"]:
    name = f["name"]
    ftype = f["type"]
    fid = f["id"]
    # הדגשה לכל שדה שהמילה "תמלול" מופיעה בו
    star = " ⭐" if "תמלול" in name else ""
    print(f"     {name:<35} | {ftype:<20} | {fid}{star}")

print()
