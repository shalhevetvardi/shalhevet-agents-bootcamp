#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_calc_pilot_cost.py — חישוב מדויק של עלות ה-pilot.

מושך את 5 השורות שיש להן חילוץ_סטטוס = הצליח, סופר tokens של ה-input
(system + user + transcript) וה-output (JSON שחזר), ומחשב עלות לפי תמחור
claude-opus-4-6.

הרצה:
    python3 _calc_pilot_cost.py
"""

import os
import sys
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv


# תמחור Opus 4.6 (USD per 1M tokens) — מקור: anthropic.com/pricing
PRICE_INPUT_PER_M = 15.0
PRICE_OUTPUT_PER_M = 75.0
USD_TO_ILS = 3.7  # שער נפוץ; להמרה גסה בלבד

MODEL = "claude-opus-4-6"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "extract_interview_system.md"

USER_MESSAGE_TEMPLATE = """להלן תמלול מלא של ראיון קבלה של שלהבת ורדי עם מועמד/ת לתוכנית טירונות סוכנים.
החזר פלט JSON יחיד לפי הסכמה שהוגדרה ב-system prompt.

---
תמלול:
{TRANSCRIPT_CONTENT}"""

# שמות שדות
F_TRANSCRIPT = "תמלול השיחה"
F_JSON = "חילוץ_JSON"
F_STATUS = "חילוץ_סטטוס"
STATUS_OK = "הצליח"


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    airtable_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_id = os.getenv("AIRTABLE_TABLE_ID")
    if not all([anthropic_key, airtable_key, base_id, table_id]):
        print("❌ חסר משתנה סביבה ב-.env")
        return 1

    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    client = Anthropic(api_key=anthropic_key)

    # שולף את כל השורות
    records: list[dict] = []
    offset = None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(
            f"https://api.airtable.com/v0/{base_id}/{table_id}",
            headers={"Authorization": f"Bearer {airtable_key}"},
            params=params,
        )
        r.raise_for_status()
        d = r.json()
        records.extend(d.get("records", []))
        offset = d.get("offset")
        if not offset:
            break

    succeeded = [r for r in records if r.get("fields", {}).get(F_STATUS) == STATUS_OK]
    print(f"נמצאו {len(succeeded)} שורות עם חילוץ_סטטוס = {STATUS_OK}\n")

    if not succeeded:
        print("אין שורות מוצלחות לחישוב.")
        return 0

    total_input = 0
    total_output = 0

    print(f"{'#':<3} {'record_id':<20} {'in_tokens':>10} {'out_tokens':>11} {'$ in':>7} {'$ out':>7} {'$ total':>8}")
    print("-" * 70)

    for i, rec in enumerate(succeeded, start=1):
        rid = rec["id"]
        fields = rec.get("fields", {})
        transcript = fields.get(F_TRANSCRIPT, "") or ""
        json_out = fields.get(F_JSON, "") or ""

        # סופר input tokens (system + user message)
        user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
        in_resp = client.messages.count_tokens(
            model=MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        in_tok = in_resp.input_tokens

        # סופר output tokens (ה-JSON ששמרנו)
        out_resp = client.messages.count_tokens(
            model=MODEL,
            messages=[{"role": "user", "content": json_out}],
        )
        out_tok = out_resp.input_tokens  # זה למעשה המחיר אם זה היה נשלח כ-input,
                                         # אבל ספירת tokens של טקסט = ספירת tokens.

        cost_in = in_tok * PRICE_INPUT_PER_M / 1_000_000
        cost_out = out_tok * PRICE_OUTPUT_PER_M / 1_000_000

        total_input += in_tok
        total_output += out_tok

        print(f"{i:<3} {rid:<20} {in_tok:>10,} {out_tok:>11,} "
              f"${cost_in:>6.3f} ${cost_out:>6.3f} ${cost_in + cost_out:>7.3f}")

    total_cost_usd = (total_input * PRICE_INPUT_PER_M + total_output * PRICE_OUTPUT_PER_M) / 1_000_000
    total_cost_ils = total_cost_usd * USD_TO_ILS

    print("-" * 70)
    print(f"\nסך input tokens : {total_input:>10,}")
    print(f"סך output tokens: {total_output:>10,}")
    print(f"\nעלות input  : ${total_input * PRICE_INPUT_PER_M / 1_000_000:.4f}")
    print(f"עלות output : ${total_output * PRICE_OUTPUT_PER_M / 1_000_000:.4f}")
    print(f"━" * 35)
    print(f"💰 עלות כוללת ל-{len(succeeded)} שורות: ${total_cost_usd:.3f}  (~₪{total_cost_ils:.2f})")
    print()
    print(f"הערכה ל-72 שורות נוספות (לפי ממוצע): "
          f"~${total_cost_usd / len(succeeded) * 72:.2f}  (~₪{total_cost_ils / len(succeeded) * 72:.0f})")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
