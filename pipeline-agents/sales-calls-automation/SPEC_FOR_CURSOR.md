# מפרט עדכוני קוד — Pipeline שיחות מכירה

> **לקרסור:** המפרט הזה מתאר 3 שינויים שצריכים להתבצע יחד. לאחר סיום העבודה,
> צריך להחזיר את הקבצים המעודכנים לקלוד (Claude) בתוך אותה שיחה / cowork session
> לבדיקה ואינטגרציה סופית. אל תריץ את ה־pipeline בעצמך — קלוד יעשה זאת.

---

## רקע

ה־pipeline עבר שני שינויים מבניים שעדיין לא חוטו ב־3 הקבצים שלמטה:

1. **`modules/analyze.py` שונה** — `ClaudeAnalyzer.analyze()` מחזיר עכשיו
   `Tuple[Dict, str]` (insights_dict, pretty_json), ולא מחרוזת.
   `EmailComposer.compose()` מקבל `insights: Dict` (לא `transcript: str`)
   ומחזיר `Dict` עם 3 מפתחות: `subject`, `personal_opening`, `promise_line`.
2. **`modules/render_email.py` נוסף** — מספק את `render_email(...)` שבונה את
   ה־HTML הסופי מ־template + בלוקים. מחזיר dict עם
   `{subject, html, logo_bytes, logo_cid, track}`.

צריך לחבר את שני אלה דרך:
- `modules/email_draft.py` — לבנות MIME עם CID + PDF
- `modules/twilio_sync.py` — להעביר את ה־dict וה־pretty JSON במקומות הנכונים
- `sales_pipeline.py` — לדלג על שיחות ללא תמלול, ולהעביר נתיבים חדשים

---

## נתיבים קיימים ושימושיים

```
שיחות מכירה אוטומציה/
├── sales_pipeline.py            # entry point
├── config.json
├── modules/
│   ├── analyze.py               # ✅ הוחלף (אל תיגע)
│   ├── render_email.py          # ✅ נוצר (אל תיגע)
│   ├── email_draft.py           # 🔧 לעדכן
│   ├── twilio_sync.py           # 🔧 לעדכן
│   └── airtable_client.py       # אל תיגע
├── templates/
│   ├── track_1_accepted.html
│   ├── track_2_beginners.html
│   ├── track_3_referral.html
│   └── blocks/
│       ├── persona_1_female.html  ... persona_4_male.html
│       └── value_block_female.html / value_block_male.html
├── prompts/
│   ├── analysis.txt
│   └── email_draft.txt
└── assets/                       # ⚠️ לוודא שקיים — אם לא, ליצור
    ├── aimprove_logo.png         # לוגו ל־CID
    └── טירונות-סוכנים.pdf         # מצורף ל־track 1+2
```

> אם `assets/` עדיין לא קיים — לא ליצור קבצים, רק להפנות אליו ב־config.
> שלהבת תוודא שהקבצים שם.

---

## שינוי 1 — `modules/email_draft.py`

### מטרה
להחליף את ההרכבה הנאיבית הקיימת (`body_plain.replace("\n\n", "</p><p>")`)
בקריאה ל־`render_email()`, ולבנות MIME מסוג `multipart/mixed` שמכיל:
- `multipart/alternative` עם plain + HTML
- `image/png` של הלוגו, מסומן `Content-ID: <aimprove_logo>` ו־`Content-Disposition: inline`
- `application/pdf` של מסמך הטירונות (רק ל־track 1 ו־2)

### חתימה חדשה של `create_draft`

```python
def create_draft(
    self,
    to_email: str,
    lead_name: str,
    insights: Dict[str, Any],          # dict שהוחזר מ־analyzer.analyze()
    templates_dir: Path,
    logo_path: Optional[Path] = None,
    pdf_path: Optional[Path] = None,
) -> str:                               # מחזיר draft_id
```

> שים לב: **אין יותר** פרמטר `transcript` ב־create_draft. התמלול כבר נוצל
> בשלב ה־analyze ואין לו שימוש כאן.

### לוגיקה צעד־צעד

1. **חבר את 3 השדות הדינמיים:**
   ```python
   composed = self.composer.compose(lead_name=lead_name, insights=insights)
   ```

2. **הרכב את ה־HTML הסופי:**
   ```python
   from modules.render_email import render_email
   rendered = render_email(
       lead_full_name=lead_name,
       insights=insights,
       composed=composed,
       templates_dir=templates_dir,
       logo_path=logo_path,
   )
   # rendered = {"subject": ..., "html": ..., "logo_bytes": ..., "logo_cid": "aimprove_logo", "track": int}
   ```

3. **בנה plain fallback** — נוסחה פשוטה שמרכיבה את הטקסט החיוני בלבד
   (לקוראי טקסט/Spam filters). דוגמה:
   ```python
   plain = (
       f"היי {lead_name.split()[0] if lead_name else ''},\n\n"
       f"{composed['personal_opening']}\n\n"
       f"{composed['promise_line']}\n\n"
       f"— שלהבת, אִימפּרוּב"
   )
   ```

4. **בנה MIME structure:**
   ```python
   from email.mime.multipart import MIMEMultipart
   from email.mime.text import MIMEText
   from email.mime.image import MIMEImage
   from email.mime.application import MIMEApplication

   msg = MIMEMultipart("mixed")
   msg["To"] = to_email
   msg["From"] = self.from_address           # כבר קיים בקלאס
   msg["Subject"] = rendered["subject"]

   alt = MIMEMultipart("alternative")
   alt.attach(MIMEText(plain, "plain", "utf-8"))
   alt.attach(MIMEText(rendered["html"], "html", "utf-8"))
   msg.attach(alt)
   ```

5. **צרף את הלוגו כ־CID** — רק אם יש bytes:
   ```python
   if rendered["logo_bytes"]:
       img = MIMEImage(rendered["logo_bytes"], _subtype="png")
       img.add_header("Content-ID", f"<{rendered['logo_cid']}>")
       img.add_header("Content-Disposition", "inline", filename="logo.png")
       msg.attach(img)
   ```

6. **צרף PDF — רק ל־track 1 ו־2:**
   ```python
   if rendered["track"] in (1, 2) and pdf_path and pdf_path.exists():
       pdf_bytes = pdf_path.read_bytes()
       pdf = MIMEApplication(pdf_bytes, _subtype="pdf")
       pdf.add_header(
           "Content-Disposition",
           "attachment",
           filename="טירונות-סוכנים.pdf",
       )
       msg.attach(pdf)
   ```
   > **track 3 לא מקבל PDF** — זו החלטה מאושרת.

7. **קודד ל־base64url ושלח ל־Gmail API:**
   ```python
   import base64
   raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
   draft = self.gmail_service.users().drafts().create(
       userId="me",
       body={"message": {"raw": raw}},
   ).execute()
   return draft["id"]
   ```

### Imports חדשים שנדרשים בראש הקובץ

```python
from pathlib import Path
from typing import Any, Dict, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import base64
from modules.render_email import render_email
```

### מה למחוק
- כל לוגיקת `body_plain.replace("\n\n", "</p><p>")` — לא רלוונטית יותר.
- כל בניית HTML inline בתוך הקובץ — עוברת ל־`render_email`.
- שום `transcript` לא נשאר בחתימה או בגוף הפונקציה.

### לוגינג
לשמר את ה־`log = logging.getLogger(__name__)` הקיים. להוסיף:
```python
log.info("Created draft %s for %s, track=%d", draft["id"], to_email, rendered["track"])
```

---

## שינוי 2 — `modules/twilio_sync.py`

### מה השתנה ב־upstream
`self.analyzer.analyze(transcript, lead_name)` מחזיר עכשיו **טאפל**:
`(insights_dict, insights_pretty_json)`.

### מה לעדכן
לחפש את הקטע:
```python
insights = self.analyzer.analyze(transcript, lead_name)   # ❌ ישן
```
ולהחליף ב:
```python
insights, insights_pretty = self.analyzer.analyze(transcript, lead_name)
```

לאחר מכן:
1. **הכתיבה ל־Airtable** — להשתמש ב־`insights_pretty`:
   ```python
   self.airtable.update_record(
       record_id=record_id,
       fields={"ai_insights": insights_pretty},   # JSON pretty-printed
   )
   ```
   (אם בשם השדה משתמשים ב־field ID `fldHOnZotRCU9qHpr` — להשאיר ככה.)

2. **הקריאה ל־email_drafter** — להעביר את ה־`insights` (dict), ולהוסיף 3
   פרמטרים חדשים: `templates_dir`, `logo_path`, `pdf_path`.

   החתימה החדשה של הקריאה:
   ```python
   draft_id = self.email_drafter.create_draft(
       to_email=lead_email,
       lead_name=lead_name,
       insights=insights,
       templates_dir=self.templates_dir,
       logo_path=self.logo_path,
       pdf_path=self.pdf_path,
   )
   ```

3. **קונסטרקטור של `TwilioSync`** — להוסיף 3 attributes:
   ```python
   def __init__(self, ..., templates_dir: Path, logo_path: Path, pdf_path: Path):
       ...
       self.templates_dir = templates_dir
       self.logo_path = logo_path
       self.pdf_path = pdf_path
   ```

### דילוג על שיחות ללא תמלול
**לפני** הקריאה ל־`analyzer.analyze()`, להוסיף בדיקה:
```python
if not transcript or not transcript.strip():
    log.warning("Skipping call %s — no transcript available", call_sid)
    continue   # או return, תלוי בהקשר של הלולאה
```

> **חשוב:** במצב כזה לא לעדכן את Airtable כלום, ולא ליצור draft.
> פשוט לעבור לשיחה הבאה.

---

## שינוי 3 — `sales_pipeline.py`

### מטרה
1. לטעון מ־config את הנתיבים החדשים (`templates_dir`, `logo_path`, `pdf_path`).
2. להעביר אותם ל־`TwilioSync`.

### עדכון ל־`config.json`
להוסיף בלוק חדש בשורש ה־config:
```json
{
  "paths": {
    "templates_dir": "templates",
    "logo_path": "assets/aimprove_logo.png",
    "pdf_path": "assets/טירונות-סוכנים.pdf"
  }
}
```
**לא להחליף** מפתחות קיימים — רק להוסיף את הבלוק `paths`.

### עדכון ל־`sales_pipeline.py`
ליד טעינת ה־config, להוסיף:
```python
from pathlib import Path

BASE_DIR = Path(__file__).parent
templates_dir = BASE_DIR / config["paths"]["templates_dir"]
logo_path = BASE_DIR / config["paths"]["logo_path"]
pdf_path = BASE_DIR / config["paths"]["pdf_path"]
```

ואז במופע של `TwilioSync`:
```python
twilio_sync = TwilioSync(
    # ... פרמטרים קיימים ...
    templates_dir=templates_dir,
    logo_path=logo_path,
    pdf_path=pdf_path,
)
```

### בדיקות sanity בהפעלה (אופציונלי אבל מומלץ)
בראש ה־main, אחרי טעינת ה־config:
```python
if not templates_dir.exists():
    raise FileNotFoundError(f"templates_dir missing: {templates_dir}")
if not logo_path.exists():
    log.warning("logo_path missing: %s — emails will be sent without logo", logo_path)
if not pdf_path.exists():
    log.warning("pdf_path missing: %s — track 1+2 emails will be sent without PDF", pdf_path)
```

---

## בדיקת שפיות לפני החזרה לקלוד

לפני שמחזירים — לוודא:

1. ✅ `email_draft.py` לא מכיל יותר שום `body_plain` או `replace("\n\n", ...)`.
2. ✅ `email_draft.py` לא מכיל יותר את `transcript` בחתימת `create_draft`.
3. ✅ `twilio_sync.py` קורא ל־`analyzer.analyze()` עם unpack של טאפל (פסיק בצד שמאל).
4. ✅ `twilio_sync.py` כותב ל־Airtable את `insights_pretty` (string), לא את ה־dict.
5. ✅ `twilio_sync.py` מעביר ל־`create_draft` את הפרמטר בשם `insights` (dict).
6. ✅ `twilio_sync.py` מדלג על שיחות ללא transcript לפני ה־analyze.
7. ✅ `config.json` מכיל בלוק `paths` חדש.
8. ✅ `sales_pipeline.py` מעביר את 3 הנתיבים ל־`TwilioSync`.
9. ✅ אין `import` חסרים (במיוחד `MIMEImage`, `MIMEApplication`, `Path`).

---

## מה להחזיר לקלוד

לאחר ביצוע השינויים, להחזיר לקלוד:
1. את 3 הקבצים המעודכנים: `modules/email_draft.py`, `modules/twilio_sync.py`,
   `sales_pipeline.py`.
2. את `config.json` המעודכן.
3. הודעה קצרה: "סיימתי, אפשר לבדוק" — כדי שקלוד יבצע sanity check ויריץ
   end-to-end test על שיחה אחת.

**אל תריץ את ה־pipeline בעצמך** — יש סיכון לשליחת מיילים אמיתיים. קלוד
ישתמש בליד טסט ידוע מראש.

---

## הערות סיום

- כל הנתיבים יחסיים לתיקיית הפרויקט (`שיחות מכירה אוטומציה/`).
- אם נתקלים בקובץ HTML של template שחסר בו `{logo_img}` או placeholder אחר —
  לא לתקן את ה־template, להחזיר לקלוד הערה והוא יתקן.
- אסור לשנות את `analyze.py` או `render_email.py` — הם הוסכמו והם עובדים.
