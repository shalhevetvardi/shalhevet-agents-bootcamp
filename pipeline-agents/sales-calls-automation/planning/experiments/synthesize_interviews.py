#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesize_interviews.py — סינתזת כל פלטי החילוץ (ראשי + תגובה למחיר) לדוח ממצאים גולמיים.

מצבי הרצה:
    python3 synthesize_interviews.py --dry-run   # שליפה + הרכבה + ספירת טוקנים. בלי קריאת API.
    python3 synthesize_interviews.py --run       # הרצה אמיתית: קריאה ל-Claude + שמירה + העלאה לנוטיון.

דרישות .env:
    ANTHROPIC_API_KEY, AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID

מודל: claude-opus-4-6
Temperature: 0.3
Max tokens: 32000 (v2 — הוגדל מ-16,000 אחרי שההרצה הראשונה נקטעה)

פלט v2: synthesis_output_v2_filtered.md (שם קבוע — לא דורס קבצים ישנים עם טיימסטמפ).

v2 — סינון פיבוט: שיחות במחיר 12,900 (4 שיחות מתקופת פיבוט עסקי) מסוננות החוצה
לפי price_quote_verbatim.

Guardrail: אם עלות משוערת > $5 — מחייב --force כדי להמשיך.
אם stop_reason=max_tokens — לא שומר סופי, רק גיבוי, ומחזיר קוד יציאה 3.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from anthropic import Anthropic
from dotenv import load_dotenv


# ──────────────────────────────────────────────────────────────
# קבועים
# ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent

# מודל
CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_TEMPERATURE = 0.3
CLAUDE_MAX_TOKENS = 32000  # v2: הוגדל מ-16,000 כי ההרצה הראשונה נקטעה

# v2: סינון שיחות פיבוט — 4 שיחות במחיר 12,900 (מלי אביטבול / מושיקו / יונתן גולן / מיטל דורון)
# תקופה של תמחור ומוצר שונים שלא שייכת לניתוח התוכנית הנוכחית.
PIVOT_PRICE_MARKERS = ["12,900", "12900", "12.900"]

# תמחור Opus 4.6 (USD per 1M tokens) — לפי platform.claude.com/docs (models overview)
PRICE_INPUT_PER_M = 5.0
PRICE_OUTPUT_PER_M = 25.0
USD_TO_ILS = 3.7
COST_CEILING_USD = 5.0  # אם מעבר לזה — חייב --force

# Airtable — שדות (עובדים לפי שמות, כי ה-API מחזיר fields לפי שם כברירת מחדל)

F_NAME = "שם"
F_JSON_MAIN = "חילוץ_JSON"
F_JSON_PRICE = "חילוץ_תגובה_למחיר_JSON"
F_STATUS_MAIN = "חילוץ_סטטוס"
F_RESULT = "תוצאה"
F_DURATION = "משך שיחה"
F_DATE = "תאריך"
STATUS_OK = "הצליח"

# קובץ פלט
OUTPUT_DIR = SCRIPT_DIR
OUTPUT_PREFIX = "synthesis_output_"
OUTPUT_V2_NAME = "synthesis_output_v2_filtered.md"  # v2: שם קבוע כדי לא לדרוס גרסאות קודמות
OUTPUT_V2_TRUNCATED_NAME = "synthesis_output_v2_TRUNCATED_BACKUP.md"  # v2: גיבוי אם stop_reason=max_tokens


# ──────────────────────────────────────────────────────────────
# SYSTEM PROMPT — מתוך prompt-sintezah (1).md, בין גדרות ה-```
# ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """אתה אנליסט בכיר של שיחות מכירה. אתה מנתח חבילה של 40+ פלטי חילוץ משני סוכנים שונים שניתחו ראיונות קבלה של מועמדים לקורס "טירונות סוכנים" של שלהבת ורדי (אימפרוב).

## מה אתה מוציא

**מסמך ממצאים גולמיים מובנה לפי 5 דלתות.** זה חומר גלם לעיבוד נוסף עם שלהבת ונתן. אתה לא כותב המלצות, לא מסכם מה צריך לעשות, ולא מחליט מי "הקהל הנכון".

## עקרונות ברזל — חובה להישמע

1. **תצפית, לא פרשנות.** "זה קרה X פעמים" — לא "זה עבד" / "זה נכון" / "זה חזק".
2. **ציטוטים וורבטים בלבד.** כולל מילוי ("כאילו", "אה"), חזרות, טעויות תמלול. אל תנקה אף פעם.
3. **דפוס = מינימום 3 שיחות שונות.** ביטוי שהופיע ב-2 שיחות בלבד אינו דפוס — הוא הערה.
4. **פילוח חובה לכל ממצא.** בלי פילוח, דפוסים מעורבים של קהלים שונים חסרי תועלת.
5. **ציטוטים מעגנים חובה.** כל ממצא צריך 2-3 ציטוטים מלאים עם שם המועמד וסיווג.
6. **"אשמח לקבל פרטים" ≠ "אשמח להצטרף".** לעולם אל תסווג הסכמה מנומסת להמשך שיחה כסגירה. זו ההנחיה הכי קריטית.
7. **שכיחות מדויקת.** X מתוך Y, לא "רוב" / "כמה" / "הרבה".
8. **אם הדאטה חסרה או מעורבת — כתוב זאת במפורש.** אל תמציא ממצאים.

## קטגוריות פילוח חובה — לכל ממצא

### א. source_of_warmth (מהחילוץ הראשי)
- past_student — תלמיד עבר
- podcast — מאזין פודקאסט
- instagram — עוקב אינסטגרם
- mix — שילוב
- unclear — לא נאמר

### ב. employee_or_business_owner (מהחילוץ הראשי)
- business_owner — בעל/ת עסק
- solo_practitioner — עצמאי/ת
- employee — שכיר/ה
- unclear

### ג. conversation_part (לממצאי שפה/אנרגיה)
- opening
- needs_discovery
- price_response
- closing

---

## הפלט מתחיל עם זה — התפלגות בסיסית

לפני שאתה נכנס לדלתות, ספק את המפתח הזה:

# סינתזת ממצאים — ראיונות קבלה טירונות סוכנים

**מספר שיחות מנותחות:** X
**שיחות עם איכות תמלול טובה:** Y
**שיחות שהגיעו לשלב מחיר:** Z

## התפלגות מקור חימום
- past_student: N (%)
- podcast: N (%)
- instagram: N (%)
- mix: N (%)
- unclear: N (%)

## התפלגות business_owner/employee
- business_owner: N (%)
- solo_practitioner: N (%)
- employee: N (%)
- unclear: N (%)

## התפלגות what_candidate_explicitly_agreed_to (מחילוץ תגובה למחיר)
- to_join: N (%)
- to_receive_details: N (%)
- to_think_about_it: N (%)
- to_consult_someone: N (%)
- to_schedule_follow_up: N (%)
- nothing_explicit: N (%)
- unclear: N (%)

## התפלגות המחיר שצוטט
הסוכן מחלץ את הציטוט הוורבטי של המחיר מהשיחה. ספור כמה שיחות ציטטו 7,900, כמה 6,500, כמה מחיר אחר, כמה לא ברור. אם יש ציטוט מחיר שלא תואם לתמחור הרשמי (7,900 / 6,500 עם הטבה) — סמן את זה במפורש כ"לבדיקת שלהבת: ייתכן שגיאת תמלול".

## הערות איכות
- שיחות שנפסלו מניתוח: X
- שיחות עם חילוץ תגובה למחיר חסר (price_mentioned=false): X
- אי-ודאויות עיקריות שעלו: [...]

---

## 🚪 דלת 1: שפה מדויקת

**מה לחפש:** ביטויים, מטאפורות, "heavy_words" ורגעים רגשיים שחוזרים על פני שיחות. מקור: door_1_language בחילוץ הראשי.

**שים לב לסוגים הבאים — הם עלו כבר בפיילוט ויש להם חשיבות מיוחדת:**
- ביטויי חמימות כלליים ("תודה", "בסדר", "יופי") — במיוחד כשהם חוזרים 3+ פעמים ב-turn אחד או על פני turns קרובים
- ביטויי אי-ודאות ("אני לא יודעת", "אני לא בטוחה", "אולי", "אני אחשוב")
- ביטויי דחייה-רכה ("תשלחי לי פרטים", "נחזור אלייך", "אני אקבל את הכל במייל")
- ביטויי נחישות אמיתית ("תרשמי אותי", "אני רוצה להצטרף", "בוא נסגור") — ציין את אלה בנפרד, הם הכי משמעותיים

**מבנה ממצא:**

### ממצא 1.X: [שם הביטוי או התבנית]
- **שכיחות:** X מתוך Y שיחות
- **פילוח:** [איפה בלט יותר — לפי source_of_warmth / business_owner / שלב בשיחה]
- **ציטוטים מעגנים:**
  - "..." — [שם, סיווג]
  - "..." — [שם, סיווג]
  - "..." — [שם, סיווג]
- **תצפית נלווית:** [נייטרלית — למשל, "הופיע רק בחלק closing" או "כל המופעים אצל employee"]

---

## 🚪 דלת 2: מפת Use Cases

**מה לחפש:** מה המועמדים אומרים שהם רוצים לבנות / ללמוד. מקור: door_2_use_cases בחילוץ הראשי.

**קיבוץ לפי:**
- domain (operations / marketing / sales / finance / content / other)
- classification (specific_agent / specific_automation / broader_system / wants_to_understand)
- concreteness (very_concrete / medium / vague)

**פילוח חובה:** לפי business_owner vs employee vs solo_practitioner, ולפי source_of_warmth.

**שים לב במיוחד:**
- מועמדים שהציגו use case קונקרטי ומפורט vs מועמדים שהשתמשו בביטויים כלליים ("לייעל תהליכים", "לחסוך זמן", "להתחבר יותר")
- domain שחוזר אצל קהל ספציפי (למשל, אם כל ה-business_owners מדברים על operations)

**מבנה ממצא:**

### ממצא 2.X: [קטגוריית use case]
- **שכיחות:** X מתוך Y שיחות
- **domain דומיננטי:** [...]
- **classification דומיננטי:** [...]
- **רמת concreteness:** X very_concrete, Y medium, Z vague
- **פילוח:** [...]
- **ציטוטים מעגנים:**
  - "..." — [שם, סיווג]
  - "..." — [שם, סיווג]
  - "..." — [שם, סיווג]

---

## 🚪 דלת 3: התנגדויות והיסוסים

**מה לחפש:** היסוסים, התנגדויות, ושאלות שמסתירות חשש. מקורות: door_3_objections בחילוץ הראשי + hesitations_or_objections_after_price בחילוץ תגובה למחיר.

**קיבוץ לפי type:**
- price
- time
- fit_doubt
- level_fear
- needs_approval (צריך להתייעץ עם מישהו)
- format
- other

**פילוח חובה:** באיזה רגע עלתה (opening / needs_discovery / price_response / closing), באיזו קטגוריית מועמד, ומה resolution_in_conversation אמר (closed / partially / not_closed / candidate_dropped_topic).

**דגשים מיוחדים:**
- ציין שיחות שבהן מועמד העלה 3+ היסוסים שונים — זה דפוס בעל משמעות
- ציין שיחות שבהן היסוס עלה רק אחרי המחיר, לא לפני
- ציטט את תגובות שלהבת בנפרד (שדה shalhevet_response_quote) — בלי לסווג אם הן "עבדו" או לא

**מבנה ממצא:**

### ממצא 3.X: [סוג התנגדות]
- **שכיחות:** X מתוך Y שיחות
- **פילוח:** [קהל שבו בולט, שלב בשיחה שבו עולה]
- **ניסוחים חוזרים:**
  - "..." — [שם, שלב, type]
  - "..." — [שם, שלב, type]
  - "..." — [שם, שלב, type]
- **תגובות שלהבת (ציטוטים נייטרליים, ללא הערכה):**
  - "..." — בתגובה לציטוט 1
  - "..." — בתגובה לציטוט 2
- **resolution distribution:** X closed, Y partially, Z not_closed, W candidate_dropped_topic

---

## 🚪 דלת 4: שינויי אנרגיה ותגובה למחיר

**מה לחפש:** רגעים של warmed_up ו-cooled_down. מקורות: door_4_energy_shifts בחילוץ הראשי + observable_signals_after_price בחילוץ תגובה למחיר.

**חלק חשוב: התנהגות לאחר המחיר**

זה החלק שהכי חשוב לסנתז בקפידה, כי אחרי אזכור המחיר יש דפוסים עדינים שמסגירים את ההתנהגות האמיתית.

**תצפיות שכדאי לחפש:**

1. **Turn length trend** (turn_length_after_price.trend):
   - ספור כמה שיחות got_shorter / stayed_same / got_longer / mixed
   - השווה ל-compared_to_earlier_in_call

2. **שאלות המועמד אחרי המחיר:**
   - שאלות לוגיסטיות (מתי, איפה, באיזה פורמט) vs שאלות על הערך/תוכן
   - רוב המועמדים שלא שאלו שום שאלה אחרי המחיר — זה דפוס גם כן

3. **סוג first_candidate_reaction:**
   - question vs statement vs acknowledgment vs silence vs hesitation
   - ספור את ההתפלגות

4. **חזרה על ביטויי חמימות כלליים:**
   - "תודה" × 3+, "בסדר" × 3+, וכו' — ציין שיחות שבהן זה קורה

5. **what_shalhevet_offered_that_candidate_did_NOT_explicitly_accept:**
   - שדה קריטי שמתעד פערים בין הצעה לבין הסכמה. ספור שיחות שיש בהן פער כזה, וצטט דוגמאות.

**אסור:**
- להסביר **למה** האנרגיה השתנתה
- לקבוע אם מועמד היה "מתלהב" או "מסויג" — רק לצטט את התצפיות

**מבנה ממצא:**

### ממצא 4.X: [דפוס]
- **שכיחות:** X מתוך Y שיחות שהגיעו לשלב מחיר
- **תצפית:** [תיאור נייטרלי של מה שקרה]
- **ציטוטים מעגנים:**
  - "..." — [שם, observable_signal]
  - "..." — [שם, observable_signal]
  - "..." — [שם, observable_signal]
- **הקשר נוסף:** [אם רלוונטי — למשל, "ב-3 מתוך 4 המקרים מועמד היה employee"]

---

## 🚪 דלת 5: בדיקת הנחות

עבור כל הנחה — ספור כמה שיחות **מאמתות**, כמה **סודקות**, כמה **לא רלוונטיות**. 2-3 ציטוטים מעגנים לכל צד.

### הנחה 5.1: "L4 מגיעים לשיחות"

רוב המועמדים הם משתמשי AI מתקדמים עם use cases קונקרטיים, לא משתמשי ChatGPT בסיסיים.

- **מאמתות:** מועמדים עם use case קונקרטי, שימוש בשפה מקצועית (סוכן / אוטומציה / אינטגרציה / MCP), אזכור כלים (Claude / Gemini / Make / Zapier).
- **סודקות:** שפה כללית בלבד ("לייעל", "לחסוך זמן"), use cases ב-concreteness=vague, חוסר היכרות עם מושגי הבסיס של סוכנים.

### הנחה 5.2: "בעלי עסקים לא נבהלים ממחיר"

התנגדויות מחיר מופיעות בעיקר אצל שכירים.

- **מאמתות:** business_owners ללא objection_type=price.
- **סודקות:** business_owners עם objection_type=price או עם תגובה "מנומסת-מקוצרת" אחרי המחיר (ביטויי תודה חוזרים, turns קצרים).
- **הערה:** ספור גם דפוסי "לא-מחיר": נניח, אם כל ה-business_owners שלא סגרו התרכזו ב-fit_doubt, זה רלוונטי לציין.

### הנחה 5.3: "מועמדים שואלים על מחיר מוקדם"

דפוס של "כמה עולה?" בשלב opening או needs_discovery.

- **מאמתות:** שיחות שבהן המועמד יזם את שאלת המחיר לפני ששלהבת הציגה.
- **סודקות:** שיחות שבהן שלהבת יזמה (price_mentioned הופיע בעיתוי שנובע מהצורך של שלהבת, לא מבקשת המועמד).

### הנחה 5.4: "מועמדים סוגרים בשיחה" — הכי קריטית

מועמדים שעברו אישור התאמה מתחייבים להצטרף במהלך השיחה עצמה.

- **מאמתות:** what_candidate_explicitly_agreed_to = to_join, עם ציטוט מפורש של "תרשמי אותי" / "אני רוצה להצטרף" / "בוא נסגור".
- **סודקות:** כל שאר הערכים — to_receive_details, to_think_about_it, to_consult_someone, to_schedule_follow_up, nothing_explicit, unclear.
- **הערה חשובה:** ביטויים כמו "אנחנו נשמח", "בשמחה רבה", "תודה רבה" — גם אם הם נשמעים חמים — **אינם** הסכמה להצטרף, אלא אם יש ציטוט מפורש של הרשמה. אם אתה לא בטוח — רשום "unclear" ולא "to_join".
- **ההנחה הזו משנה אסטרטגיה שלמה.** אם היא נסדקת, זה יקבע איך נבנים המסלולים אחרי השיחה (מייל, סוכן, מסגור, הטבה). חובה לצטט 3+ דוגמאות לכל צד.

### הנחה 5.5: "מועמדים פותחים במחמאות לשלהבת"

פתיחה רגשית — "אני עוקב", "אני מעריץ", "הפודקאסט שלך מדהים".

- **מאמתות:** פתיחות שיחה מסוג זה.
- **סודקות:** פתיחות עסקיות / ענייניות.
- **פילוח חובה:** האם זה דפוס של source_of_warmth ספציפי (podcast / past_student)?

### הנחה 5.6: "מועמדים מבקשים לדבר עם שלהבת לפני החלטה"

תבנית של "אני רוצה לשמוע ממנה קודם".

- **מאמתות:** שיחות שבהן המועמד ביקש המשך ישיר עם שלהבת.
- **סודקות:** שיחות שבהן המועמד החליט בלי לבקש את זה.

### הנחה 5.7: "'המתחיל במסווה' מגיע לשיחות"

מועמדים שנשמעים מתקדמים אבל ה-use cases שלהם בסיסיים.

- **מאמתות:** מועמדים עם שפה מקצועית + classification=wants_to_understand / concreteness=vague.
- **סודקות:** מועמדים עם use cases קונקרטיים ומפורטים, ו-concreteness=very_concrete / medium.

### הנחה 5.8: "פער בין הצהרת רצון לבין התנהגות"

מועמדים שהתלהבו במהלך השיחה אבל לא התחייבו אחרי המחיר.

- **מאמתות:** מינימום 2 warmed_up ב-door_4_energy_shifts + what_candidate_explicitly_agreed_to שאינו to_join.
- **סודקות:** עקביות בין התלהבות לסגירה, או בין ריחוק לאי-סגירה.
- **צטט במיוחד:** שדה what_shalhevet_offered_that_candidate_did_NOT_explicitly_accept — שם מתועדים פערים כאלה במפורש.

### הנחה 5.9: "שלהבת מציעה הטבה פרואקטיבית גם כשהמועמד לא שאל על מחיר"

- **מאמתות:** ציטוט ה-price_quote_verbatim כולל גם את המחיר המלא (7,900) וגם את ההטבה (6,500) בתור הצעה פרואקטיבית של שלהבת.
- **סודקות:** ציטוט ה-price_quote_verbatim מציין רק את המחיר המלא, או שההטבה הוצעה רק אחרי שאלה/התנגדות של המועמד.

### הנחה 5.10: "ירידה חדה באורך ה-turn אחרי המחיר = סיגנל התרחקות"

- **מאמתות:** turn_length_after_price.trend = got_shorter + compared_to_earlier_in_call = significantly_shorter + what_candidate_explicitly_agreed_to שאינו to_join.
- **סודקות:** שיחות עם ירידה באורך אבל כן to_join, או שיחות ללא ירידה אבל שלא סגרו.

**מבנה כל הנחה:**

### הנחה 5.X: [ניסוח]
- **מאמתות:** X שיחות
  - "..." — [שם, פילוח]
  - "..." — [שם, פילוח]
  - "..." — [שם, פילוח]
- **סודקות:** Y שיחות
  - "..." — [שם, פילוח]
  - "..." — [שם, פילוח]
  - "..." — [שם, פילוח]
- **לא רלוונטיות / לא מספיק דאטה:** Z שיחות
- **תצפית נייטרלית:** [הנחה מחזיקה / נסדקת / לא מספיק דאטה / מעורב]

---

## סעיף אחרון: שאלות פתוחות לעיבוד בשלב 6

זה סעיף חופשי לתצפיות שעלו בדאטה ולא התאימו בדיוק לדלתות או להנחות. כאן אתה יכול לסמן:

1. **דפוסים מפתיעים** שלא צפויים ולא חלק מאף הנחה — אבל בלי לפרש מה הם אומרים.
2. **פערי דאטה** שכדאי לטפל בהם בעתיד (למשל, אם source_of_warmth היה unclear ב-60% מהשיחות).
3. **חוסר עקביות אפשרי בדאטה** — למשל, אם בחילוץ של שיחה מסוימת יש ציטוט מחיר שלא תואם (12,900 במקום 7,900) — זה עלול להיות שגיאת תמלול. סמן ואל תתקן.
4. **שיחות יוצאות דופן** — אם יש שיחה שהציגה תבנית ייחודית לא-שכיחה, ציין אותה בנפרד כ-"case study" ללא ההכללה שהיא מעידה על דפוס.

---

## חוקי פלט טכניים

1. **פלט במרקדאון בלבד.** בלי JSON, בלי HTML.
2. **כותרות מדויקות** לפי המבנה למעלה. אל תוסיף כותרות חדשות ברמת top-level. תוכל להוסיף ממצאים רבים בתוך כל דלת.
3. **ציטוטים בעברית** כפי שהיו בדאטה, כולל טעויות תמלול.
4. **שמות מועמדים** כפי שמופיעים בשדה candidate_name_if_mentioned. אם אין שם — השתמש ב-record_id או סמן "אנונימי".
5. **מספרים מדויקים** — תמיד X מתוך Y.
6. **אם דלת חסרה דאטה משמעותי** — כתוב זאת במפורש. אל תמציא ממצאים.
7. **אין המלצות בשום מקום.** אתה עובד עם דאטה, לא עם אסטרטגיה.

---

## הקלט שלך

להלן חבילת פלטי חילוץ מ-[X] שיחות. כל שיחה כוללת:
- מטא-דאטה: שם, משך, תאריך, תוצאה סופית (טיוטה מוכנה / זכר / סגר)
- פלט חילוץ ראשי (JSON עם 8 מפתחות)
- פלט חילוץ תגובה למחיר (JSON עם התנהגות אחרי מחיר)

קרא את הכל. זהה דפוסים. בנה את המסמך לפי המבנה למעלה.

**זכור:** אתה מוציא דאטה גולמית מאורגנת. לא תובנות סופיות. לא המלצות פעולה. לא החלטות אסטרטגיות.

---

[SYNTHESIS_DATA_HERE]
"""


# User message פשוטה — הסינתזה נעשית כולה דרך ה-system prompt
USER_MESSAGE = "בצע את הסינתזה לפי ההנחיות ב-system prompt. החזר מסמך markdown מלא לפי המבנה שהוגדר."


# ──────────────────────────────────────────────────────────────
# פונקציות עזר
# ──────────────────────────────────────────────────────────────

def load_env() -> dict:
    load_dotenv(SCRIPT_DIR / ".env")
    return {
        "anthropic_key": os.getenv("ANTHROPIC_API_KEY"),
        "airtable_key": os.getenv("AIRTABLE_API_KEY"),
        "base_id": os.getenv("AIRTABLE_BASE_ID"),
        "table_id": os.getenv("AIRTABLE_TABLE_ID"),
    }


def fetch_all_records(base_id: str, table_id: str, airtable_key: str) -> list:
    """מושך את כל השורות מהטבלה, page-by-page."""
    records = []
    offset = None
    url = f"https://api.airtable.com/v0/{base_id}/{table_id}"
    headers = {"Authorization": f"Bearer {airtable_key}"}
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        records.extend(d.get("records", []))
        offset = d.get("offset")
        if not offset:
            break
    return records


def filter_successful(records: list) -> list:
    """רק שורות עם חילוץ_סטטוס = הצליח."""
    return [
        r for r in records
        if r.get("fields", {}).get(F_STATUS_MAIN) == STATUS_OK
    ]


def filter_out_pivot_prices(records: list) -> tuple[list, list]:
    """
    v2: מסנן החוצה שיחות פיבוט שבהן price_quote_verbatim מכיל 12,900.
    מזהה דרך parse של F_JSON_PRICE, עם fallback לחיפוש בטקסט הגולמי.
    מחזיר (kept, removed).
    """
    kept = []
    removed = []
    for r in records:
        f = r.get("fields", {})
        price_json_str = (f.get(F_JSON_PRICE) or "").strip()
        is_pivot = False
        quote_found = ""
        if price_json_str:
            try:
                price_data = json.loads(price_json_str)
                quote = str(price_data.get("price_quote_verbatim") or "")
                if any(m in quote for m in PIVOT_PRICE_MARKERS):
                    is_pivot = True
                    quote_found = quote
            except (json.JSONDecodeError, TypeError):
                # fallback: חיפוש בגולמי
                if any(m in price_json_str for m in PIVOT_PRICE_MARKERS):
                    is_pivot = True
                    quote_found = "(parse failed — נמצא בגולמי)"
        if is_pivot:
            name = f.get(F_NAME) or "אנונימי"
            removed.append({"name": name, "quote": quote_found, "record": r})
        else:
            kept.append(r)
    return kept, removed


def format_duration(val) -> str:
    """משך שיחה ב-Airtable הוא לרוב שניות. מחזיר תיאור קריא."""
    if val is None or val == "":
        return "לא ידוע"
    try:
        seconds = float(val)
        minutes = int(seconds // 60)
        rem = int(seconds % 60)
        return f"{minutes}:{rem:02d} דקות"
    except (TypeError, ValueError):
        return str(val)


def format_date(val) -> str:
    if not val:
        return "לא ידוע"
    return str(val).split("T")[0]  # חותך זמן אם יש


def assemble_payload(records: list) -> str:
    """בונה את הבלוק של כל השיחות לפי הפורמט המוגדר בבריף."""
    blocks = []
    for i, rec in enumerate(records, start=1):
        f = rec.get("fields", {})
        name = f.get(F_NAME) or "אנונימי"
        duration = format_duration(f.get(F_DURATION))
        date = format_date(f.get(F_DATE))
        result = f.get(F_RESULT) or "לא ידוע"
        json_main = (f.get(F_JSON_MAIN) or "").strip() or "{}"
        json_price = (f.get(F_JSON_PRICE) or "").strip() or "{}"

        block = (
            f"[שיחה {i}]\n"
            f"שם: {name}\n"
            f"משך: {duration}\n"
            f"תאריך: {date}\n"
            f"תוצאה סופית: {result}\n"
            f"\n"
            f"חילוץ ראשי:\n"
            f"{json_main}\n"
            f"\n"
            f"חילוץ תגובה למחיר:\n"
            f"{json_price}\n"
            f"\n"
            f"---\n"
        )
        blocks.append(block)

    return "\n".join(blocks)


def build_full_system_prompt(data_payload: str) -> str:
    """מחליף את [SYNTHESIS_DATA_HERE] בתוך הפרומפט."""
    return SYSTEM_PROMPT.replace("[SYNTHESIS_DATA_HERE]", data_payload)


def count_input_tokens(client: Anthropic, full_system: str) -> int:
    resp = client.messages.count_tokens(
        model=CLAUDE_MODEL,
        system=full_system,
        messages=[{"role": "user", "content": USER_MESSAGE}],
    )
    return resp.input_tokens


def estimate_cost_usd(input_tokens: int, estimated_output_tokens: int = CLAUDE_MAX_TOKENS) -> dict:
    in_cost = input_tokens * PRICE_INPUT_PER_M / 1_000_000
    # הערכה: הפלט לא בהכרח מגיע ל-max_tokens, אבל נעדיף הערכה שמרנית
    out_cost_max = estimated_output_tokens * PRICE_OUTPUT_PER_M / 1_000_000
    return {
        "input_tokens": input_tokens,
        "input_cost_usd": in_cost,
        "output_max_cost_usd": out_cost_max,
        "total_max_cost_usd": in_cost + out_cost_max,
    }


def save_output_locally(content: str, filename: Optional[str] = None) -> Path:
    """אם filename ניתן — שם קבוע. אחרת — טיימסטמפ."""
    if filename:
        path = OUTPUT_DIR / filename
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = OUTPUT_DIR / f"{OUTPUT_PREFIX}{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path


def call_claude(client: Anthropic, full_system: str) -> tuple[str, dict, str]:
    """
    הקריאה האמיתית ל-API ב-STREAMING. מחזיר (text, usage_dict, stop_reason).
    streaming חובה כי בקשות עם max_tokens גדול עלולות לעבור 10 דקות,
    וה-SDK חוסם non-streaming מעל הסף הזה.
    retry אחד אם נכשל.
    """
    for attempt in (1, 2):
        try:
            text_parts: list = []
            chars_since_dot = 0
            print("   📡 streaming: ", end="", flush=True)
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                temperature=CLAUDE_TEMPERATURE,
                system=full_system,
                messages=[{"role": "user", "content": USER_MESSAGE}],
            ) as stream:
                for chunk in stream.text_stream:
                    text_parts.append(chunk)
                    chars_since_dot += len(chunk)
                    # נקודה כל ~1000 תווים — כדי שתראי שזז
                    while chars_since_dot >= 1000:
                        print(".", end="", flush=True)
                        chars_since_dot -= 1000
                final = stream.get_final_message()
            print()  # newline אחרי הנקודות

            text = "".join(text_parts).strip()
            usage = {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            }
            stop_reason = getattr(final, "stop_reason", "unknown") or "unknown"
            return text, usage, stop_reason
        except Exception as e:  # noqa: BLE001
            print()  # newline אם היינו באמצע נקודות
            print(f"⚠️  attempt {attempt} failed: {e}", file=sys.stderr)
            if attempt == 2:
                raise
            time.sleep(5)
    # unreachable
    return "", {}, "unknown"


# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="סינתזת ראיונות קבלה — dry-run או run מלא."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="שליפה + הרכבה + ספירת טוקנים. בלי קריאה ל-API.")
    group.add_argument("--run", action="store_true",
                       help="הרצה אמיתית עם קריאה ל-API ושמירה מקומית.")
    parser.add_argument("--force", action="store_true",
                        help="עוקף את תקרת העלות ($5).")
    args = parser.parse_args()

    env = load_env()
    missing = [k for k in ("anthropic_key", "airtable_key", "base_id", "table_id") if not env[k]]
    if missing:
        print(f"❌ חסרים משתני סביבה: {missing}", file=sys.stderr)
        return 1

    client = Anthropic(api_key=env["anthropic_key"])

    # 1. שליפה
    print("📥 שולף שורות מאיירטייבל...")
    all_records = fetch_all_records(env["base_id"], env["table_id"], env["airtable_key"])
    succeeded = filter_successful(all_records)
    print(f"   סה״כ שורות: {len(all_records)}")
    print(f"   עם חילוץ_סטטוס = '{STATUS_OK}': {len(succeeded)}")

    if not succeeded:
        print("❌ אין שורות מוצלחות — אין מה לסנתז.", file=sys.stderr)
        return 1

    # כמה מהן גם יש להן חילוץ_תגובה_למחיר
    with_price = sum(1 for r in succeeded if r.get("fields", {}).get(F_JSON_PRICE))
    print(f"   מתוכן גם עם חילוץ תגובה למחיר: {with_price}")

    # v2: סינון שיחות פיבוט (12,900)
    print("\n🧹 v2: מסנן החוצה שיחות פיבוט (מחיר 12,900)...")
    kept, removed = filter_out_pivot_prices(succeeded)
    print(f"   סוננו החוצה: {len(removed)} שיחות")
    for item in removed:
        q_preview = (item["quote"] or "")[:120].replace("\n", " ")
        print(f"     - {item['name']}  |  {q_preview!r}")
    print(f"   נשארו לסינתזה: {len(kept)}")
    succeeded = kept  # מכאן ממשיכים רק עם הנקיים

    # 2. הרכבת חבילה
    print("\n🔧 מרכיב חבילת קלט...")
    payload = assemble_payload(succeeded)
    full_system = build_full_system_prompt(payload)
    payload_chars = len(payload)
    full_chars = len(full_system)
    print(f"   גודל payload (נתונים בלבד): {payload_chars:,} תווים")
    print(f"   גודל system prompt מלא:     {full_chars:,} תווים")

    # 3. ספירת טוקנים
    print("\n🧮 סופר טוקנים ב-input...")
    input_tokens = count_input_tokens(client, full_system)
    cost = estimate_cost_usd(input_tokens)
    print(f"   input tokens: {input_tokens:,}")
    print(f"   עלות input:          ${cost['input_cost_usd']:.3f}")
    print(f"   עלות output מקסימלית: ${cost['output_max_cost_usd']:.3f}  (אם מגיע ל-{CLAUDE_MAX_TOKENS} tokens)")
    print(f"   סה״כ תקרה משוערת:      ${cost['total_max_cost_usd']:.3f}  (~₪{cost['total_max_cost_usd'] * USD_TO_ILS:.2f})")

    # 4. אם dry-run — עצור פה
    if args.dry_run:
        print("\n" + "=" * 60)
        print("✅ DRY RUN הושלם. לא הופעלה קריאה ל-API.")
        print("=" * 60)
        print("\nלהרצה אמיתית:")
        print(f"    python3 {Path(__file__).name} --run")
        if cost["total_max_cost_usd"] > COST_CEILING_USD:
            print(f"\n⚠️  העלות המשוערת (${cost['total_max_cost_usd']:.2f}) מעל תקרת ${COST_CEILING_USD}.")
            print(f"    תצטרכי להוסיף --force להרצה אמיתית.")
        return 0

    # 5. בדיקת guardrail עלות
    if cost["total_max_cost_usd"] > COST_CEILING_USD and not args.force:
        print(f"\n🛑 העלות המשוערת (${cost['total_max_cost_usd']:.2f}) עולה על תקרת ${COST_CEILING_USD}.")
        print("    אם את בטוחה — הוסיפי --force.")
        return 2

    # 6. קריאה ל-Claude
    print("\n🤖 שולח ל-Claude Opus 4.6 (זה יכול לקחת כמה דקות)...")
    start = time.time()
    output_text, usage, stop_reason = call_claude(client, full_system)
    elapsed = time.time() - start
    print(f"   ✅ חזר תשובה ב-{elapsed:.1f} שניות")
    print(f"   🛑 stop_reason:   {stop_reason}")
    print(f"   input_tokens:  {usage['input_tokens']:,}")
    print(f"   output_tokens: {usage['output_tokens']:,}")

    # עלות אמיתית
    actual_cost = (
        usage["input_tokens"] * PRICE_INPUT_PER_M
        + usage["output_tokens"] * PRICE_OUTPUT_PER_M
    ) / 1_000_000
    print(f"   💰 עלות אמיתית: ${actual_cost:.3f}  (~₪{actual_cost * USD_TO_ILS:.2f})")

    # v2: אם נקטע בגלל max_tokens — לא שומרים לשם הסופי, רק גיבוי, ועוצרים
    if stop_reason == "max_tokens":
        print("\n" + "!" * 60)
        print(f"⚠️  ההרצה נקטעה שוב בגלל max_tokens (={CLAUDE_MAX_TOKENS:,})!")
        print("    לא שומר את הקובץ הסופי. יש לעלות ל-64,000 ולהריץ שוב.")
        backup = save_output_locally(output_text, filename=OUTPUT_V2_TRUNCATED_NAME)
        print(f"    גיבוי של הפלט הקטוע נשמר ב: {backup}")
        print("!" * 60)
        return 3

    # 7. שמירה מקומית — שם קבוע v2
    print("\n💾 שומר פלט מקומית...")
    local_path = save_output_locally(output_text, filename=OUTPUT_V2_NAME)
    print(f"   נשמר: {local_path}")

    print("\n" + "=" * 60)
    print("✅ הסתיים. (שמירה מקומית בלבד — ללא העלאה לנוטיון)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
