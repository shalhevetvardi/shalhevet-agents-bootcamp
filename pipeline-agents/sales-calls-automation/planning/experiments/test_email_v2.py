#!/usr/bin/env python3
"""
test_email_v2.py — בדיקה ידנית של הפרומפט החדש (email_draft_v2.txt) על ליד אמיתי מ-Airtable.

לא נוגע בצינור הייצור. קורא את הפרומפט החדש, שולח ל-Claude עם transcript + insights + lead_name,
מדפיס את הפלט הגולמי ואת 5 השדות בנפרד (כולל שתי גרסאות לפסקה — עם ציטוט ובלי), ושומר את ה-JSON המלא ב-state/.
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from modules.airtable_client import AirtableClient


# ---------- Helpers ----------

GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def _extract_json(text: str) -> dict:
    """מחלץ JSON מהפלט של Claude — תומך ב-fence, JSON גולמי, ו-balanced braces."""
    if not text:
        raise ValueError("empty LLM response")
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON in response: {text[:200]}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"unbalanced JSON: {text[:200]}")


def word_count(text: str) -> int:
    """סופר מילים בטקסט — מוריד תגיות HTML."""
    stripped = re.sub(r"<[^>]+>", " ", text)
    return len([w for w in stripped.split() if w.strip()])


def detect_forbidden(text: str) -> list[str]:
    """מחזיר רשימת ביטויים אסורים שהופיעו בפלט (מהרשימה של email_draft_v2)."""
    forbidden = [
        "הזדמנות",
        "יהיה שווה לך",
        "שווה לך",
        "נעים שדיברנו",
        "הרגע הנעים",
        "שמחתי מאוד",
        "נהניתי מהשיחה",
        "אדוני הנכבד",
        "היי גברת",
    ]
    hits = []
    for phrase in forbidden:
        if phrase in text:
            hits.append(phrase)
    return hits


def detect_em_dash(text: str) -> int:
    """סופר em dash (—) בטקסט."""
    return text.count("—")


# ---------- Lead Picker ----------

def load_candidate_leads(airtable: AirtableClient) -> list[dict]:
    """שולף לידים שיש להם גם transcript וגם ai_insights — מוכנים לבדיקה."""
    tr_fid = airtable.f("transcript")
    ins_fid = airtable.f("ai_insights")
    name_fid = airtable.f("name")
    gender_fid = airtable.f("gender")
    dt_fid = airtable.f("call_datetime")

    records = airtable.list_all_records(by_id=True)
    candidates = []
    for rec in records:
        fields = rec.get("fields", {})
        transcript = fields.get(tr_fid, "")
        insights_raw = fields.get(ins_fid, "")
        if not transcript or not insights_raw:
            continue
        candidates.append({
            "id": rec["id"],
            "name": fields.get(name_fid, "(ללא שם)"),
            "gender": fields.get(gender_fid, ""),
            "call_datetime": fields.get(dt_fid, ""),
            "transcript": transcript,
            "insights_raw": insights_raw,
        })
    # מיון לפי תאריך שיחה — חדש ראשון
    candidates.sort(key=lambda c: c.get("call_datetime") or "", reverse=True)
    return candidates


def _parse_selection(raw: str, max_idx: int) -> list[int]:
    """מפענחת בחירה: '1' / '1,3,5' / '1-3' / '1,3-5' / 'all'. מחזירה אינדקסים (1-based) ייחודיים וממוינים."""
    raw = raw.strip().lower()
    if raw in ("all", "a", "הכל", "כולם"):
        return list(range(1, max_idx + 1))
    picked: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            for i in range(lo, hi + 1):
                if 1 <= i <= max_idx:
                    picked.add(i)
        else:
            i = int(part)
            if 1 <= i <= max_idx:
                picked.add(i)
    return sorted(picked)


def pick_leads(candidates: list[dict]) -> list[dict]:
    print(f"\n{BOLD}{BLUE}לידים זמינים לבדיקה (עם transcript + insights):{NC}\n")
    for i, c in enumerate(candidates, 1):
        dt = c.get("call_datetime", "")[:10] if c.get("call_datetime") else "—"
        gender = c.get("gender", "") or "—"
        print(f"  {BOLD}{i:>2}.{NC}  {c['name']:<20}  {DIM}{gender:<6}  {dt}{NC}")
    print()
    print(f"{DIM}דוגמאות: 3  |  1,3,5  |  1-3  |  1,4-6  |  all{NC}")
    while True:
        choice = input(f"{GREEN}בחרי מספר/ים (או 'q' ליציאה): {NC}").strip()
        if choice.lower() in ("q", "quit", "exit"):
            print("יוצאת.")
            sys.exit(0)
        try:
            idxs = _parse_selection(choice, len(candidates))
            if idxs:
                return [candidates[i - 1] for i in idxs]
        except ValueError:
            pass
        print(f"{RED}בחירה לא תקינה. נסי שוב.{NC}")


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="בדיקת פרומפט email_draft_v2 על ליד אמיתי")
    parser.add_argument("--lead-id", help="Record ID מ-Airtable (לדלג על בחירה אינטראקטיבית)")
    parser.add_argument("--prompt", default="prompts/email_draft_v2.txt",
                        help="נתיב לפרומפט (ברירת מחדל: email_draft_v2.txt)")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR / ".env")

    # טעינת פרומפט
    prompt_path = SCRIPT_DIR / args.prompt
    if not prompt_path.exists():
        print(f"{RED}✗ פרומפט לא נמצא: {prompt_path}{NC}")
        sys.exit(1)
    system_prompt = prompt_path.read_text(encoding="utf-8")
    print(f"{DIM}פרומפט: {args.prompt} ({len(system_prompt):,} תווים){NC}")

    # חיבור ל-Airtable
    airtable = AirtableClient(
        api_key=os.environ["AIRTABLE_API_KEY"],
        base_id=os.environ["AIRTABLE_BASE_ID"],
        table_id=os.environ["AIRTABLE_TABLE_ID"],
        config_path=str(SCRIPT_DIR / "config.json"),
    )

    # בחירת לידים
    if args.lead_id:
        rec = airtable.get_record(args.lead_id)
        fields = rec.get("fields", {})
        leads = [{
            "id": rec["id"],
            "name": fields.get("שם", "(ללא שם)"),
            "transcript": fields.get("תמלול", ""),
            "insights_raw": fields.get("ai_insights", ""),
        }]
    else:
        candidates = load_candidate_leads(airtable)
        if not candidates:
            print(f"{RED}✗ לא נמצאו לידים עם transcript + insights.{NC}")
            sys.exit(1)
        leads = pick_leads(candidates)

    # הכנת Anthropic client פעם אחת — משותף לכל הלידים
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if len(leads) > 1:
        print(f"\n{BOLD}{BLUE}═══ מעבדת {len(leads)} לידים ═══{NC}")

    total = len(leads)
    succeeded = 0
    failed: list[tuple[str, str]] = []  # (lead_name, reason)

    for idx, lead in enumerate(leads, 1):
        print(f"\n{BOLD}{BLUE}{'═' * 60}{NC}")
        print(f"{BOLD}{BLUE}ליד {idx}/{total}: {lead['name']}{NC}")
        print(f"{BOLD}{BLUE}{'═' * 60}{NC}")

        try:
            ok = process_lead(lead, client, system_prompt, args.prompt)
            if ok:
                succeeded += 1
            else:
                failed.append((lead["name"], "לא עבד (ראי לוג למעלה)"))
        except Exception as e:
            print(f"{RED}✗ חריגה בעיבוד {lead['name']}: {e}{NC}")
            failed.append((lead["name"], str(e)))

    # סיכום סופי רק אם היה יותר מליד אחד
    if total > 1:
        print(f"\n{BOLD}{GREEN}═══ סיכום רץ ═══{NC}")
        print(f"  הצליחו: {GREEN}{succeeded}{NC} / {total}")
        if failed:
            print(f"  נכשלו: {RED}{len(failed)}{NC}")
            for name, reason in failed:
                print(f"    • {name}: {DIM}{reason}{NC}")
        print()


def process_lead(lead: dict, client: Anthropic, system_prompt: str, prompt_file: str) -> bool:
    """מעבדת ליד אחד: שולחת ל-Claude, מדפיסה פלט + בדיקות, שומרת state. מחזירה True אם הצליח."""
    # ניתוח ה-insights
    raw_ins = lead["insights_raw"]
    try:
        parsed = json.loads(raw_ins) if isinstance(raw_ins, str) else raw_ins
    except (json.JSONDecodeError, TypeError) as e:
        print(f"{RED}✗ insights לא JSON תקין: {e}{NC}")
        print(f"{DIM}תוכן (200 תווים ראשונים): {str(raw_ins)[:200]}{NC}")
        return False

    if isinstance(parsed, dict):
        insights = parsed
    elif isinstance(parsed, list):
        if parsed and isinstance(parsed[0], dict):
            insights = parsed[0]
            print(f"{YELLOW}⚠ ה-insights נשמר כ-list ולא כ-dict — משתמשת בפריט הראשון (מתוך {len(parsed)}).{NC}")
        else:
            print(f"{RED}✗ ה-insights הוא list שלא מכיל dict — מדלגת על הליד הזה.{NC}")
            return False
    else:
        print(f"{RED}✗ פורמט insights לא צפוי ({type(parsed).__name__}) — מדלגת.{NC}")
        return False

    lead_name = (lead["name"] or "").split()[0] if lead["name"] else ""
    transcript = lead["transcript"]

    print(f"\n{BOLD}{BLUE}═══ שולחת ל-Claude ═══{NC}")
    print(f"  ליד:       {BOLD}{lead['name']}{NC}")
    print(f"  transcript: {len(transcript):,} תווים")
    print(f"  insights:   {len(lead['insights_raw']):,} תווים")
    print(f"  track:      {insights.get('track', '?')}  persona: {insights.get('persona_id', '?')}  gender: {insights.get('gender', '?')}")
    print()

    model = "claude-sonnet-4-6"
    user_msg = (
        f"lead_name: {lead_name or 'ללא שם'}\n\n"
        f"transcript:\n---\n{transcript}\n---\n\n"
        f"JSON מהאנליסט:\n{json.dumps(insights, ensure_ascii=False, indent=2)}\n\n"
        "החזירי JSON אחד עם 5 השדות: subject, personal_opening, "
        "personal_paragraph_with_quote, personal_paragraph_without_quote, promise_line."
    )

    resp = client.messages.create(
        model=model,
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()

    try:
        composed = _extract_json(raw)
    except Exception as e:
        print(f"{RED}✗ פלט לא JSON תקין: {e}{NC}")
        print(f"{DIM}{raw[:500]}{NC}")
        return False

    # הדפסה קריאה
    print(f"{BOLD}{GREEN}═══ פלט הסוכן ═══{NC}\n")

    print(f"{BOLD}📧 subject:{NC}")
    print(f"   {composed.get('subject', '')}\n")

    print(f"{BOLD}👋 personal_opening:{NC}")
    print(f"   {composed.get('personal_opening', '')}")
    op_words = len(composed.get("personal_opening", "").split())
    op_status = GREEN if 8 <= op_words <= 20 else YELLOW
    print(f"   {op_status}({op_words} מילים — יעד 8-20){NC}\n")

    # --- פסקה אישית: שתי גרסאות ---
    def render_paragraph(label: str, para: str) -> dict:
        print(f"{BOLD}{label}:{NC}")
        if not para:
            print(f"   {RED}✗ שדה ריק — הסוכן לא החזיר גרסה הזו.{NC}\n")
            return {"words": 0, "forbidden": [], "em_dash": 0, "empty": True}

        clean = re.sub(r"<[^>]+>", "\n", para).strip()
        for line in clean.split("\n"):
            line = line.strip()
            if line:
                print(f"   {line}")

        pw = word_count(para)
        status = GREEN if 60 <= pw <= 110 else YELLOW
        print(f"\n   {status}({pw} מילים — יעד 60-110){NC}")

        fb = detect_forbidden(para)
        em = detect_em_dash(para)
        checks = []
        if fb:
            checks.append(f"{RED}✗ ביטויים אסורים: {', '.join(fb)}{NC}")
        if em:
            checks.append(f"{RED}✗ {em} em dash — צריך להחליף ב-hyphen או '..'{NC}")
        if lead_name and lead_name in para:
            checks.append(f"{RED}✗ שם הליד ('{lead_name}') מופיע בתוך הפסקה — אסור{NC}")
        if pw > 110:
            checks.append(f"{YELLOW}⚠ פסקה ארוכה מדי ({pw} > 110){NC}")
        if pw < 60:
            checks.append(f"{YELLOW}⚠ פסקה קצרה מדי ({pw} < 60){NC}")
        if checks:
            print(f"\n   {BOLD}בדיקות:{NC}")
            for c in checks:
                print(f"   {c}")
        else:
            print(f"\n   {GREEN}✓ עבר את כל הבדיקות האוטומטיות{NC}")
        print()
        return {"words": pw, "forbidden": fb, "em_dash": em, "empty": False}

    print(f"{BOLD}✍️  פסקה אישית — שתי גרסאות:{NC}\n")

    para_with = composed.get("personal_paragraph_with_quote", "")
    para_without = composed.get("personal_paragraph_without_quote", "")

    metrics_with = render_paragraph("🗣  personal_paragraph_with_quote (עם ציטוט מהתמלול)", para_with)
    metrics_without = render_paragraph("✏️  personal_paragraph_without_quote (סינתזה בלי ציטוט)", para_without)

    print(f"\n{BOLD}📎 promise_line:{NC}")
    pl = composed.get("promise_line", "")
    if pl:
        clean_pl = re.sub(r"<[^>]+>", " ", pl).strip()
        print(f"   {clean_pl}")
    else:
        print(f"   {DIM}(ריק — לא הייתה הבטחה נוספת בשיחה){NC}")

    # שמירה
    state_dir = SCRIPT_DIR / "state"
    state_dir.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w\u0590-\u05FF]+", "_", lead["name"] or "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = state_dir / f"test_v2_{safe_name}_{timestamp}.json"
    out_path.write_text(
        json.dumps({
            "lead": {"id": lead["id"], "name": lead["name"]},
            "prompt_file": prompt_file,
            "output": composed,
            "checks": {
                "opening_words": op_words,
                "with_quote": {
                    "words": metrics_with["words"],
                    "forbidden_hits": metrics_with["forbidden"],
                    "em_dash_count": metrics_with["em_dash"],
                    "empty": metrics_with["empty"],
                },
                "without_quote": {
                    "words": metrics_without["words"],
                    "forbidden_hits": metrics_without["forbidden"],
                    "em_dash_count": metrics_without["em_dash"],
                    "empty": metrics_without["empty"],
                },
            },
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{DIM}נשמר: state/{out_path.name}{NC}")
    return True


if __name__ == "__main__":
    main()
