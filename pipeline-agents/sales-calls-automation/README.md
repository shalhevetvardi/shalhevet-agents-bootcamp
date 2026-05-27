# שיחות מכירה — אוטומציה מקצה לקצה

פייפליין אוטומטי שהופך שיחת מכירה בזום/טלפון לטיוטת מייל מעקב מוכנה ב-Gmail.

## איך זה עובד

```
┌──────────────┐       ┌──────────────┐
│   Calendly   │──A──▶│   Airtable   │
│  (זימונים)   │       │  (לידים)     │
└──────────────┘       └──────────────┘
                              ▲
                              │ B
                              │
┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Twilio     │──────▶│  ivrit.ai    │──────▶│   Claude     │──────▶│  Gmail Draft │
│ (הקלטות)     │       │  (תמלול)     │       │  (ניתוח)     │       │  (טיוטה)     │
└──────────────┘       └──────────────┘       └──────────────┘       └──────────────┘
```

### Pipeline A — Calendly → Airtable (מכניס לידים אוטומטית)

כל 5 דקות הסקריפט שולף מ-Calendly את כל הזימונים (ב-30 הימים הקרובים + יום אחורה), ולכל אירוע שעדיין לא קיים ב-Airtable — יוצר רשומת ליד חדשה עם שם, טלפון, מייל, תאריך שיחה ו-Calendly URI.

### Pipeline B — Twilio → תמלול → ניתוח → טיוטת מייל

כל 5 דקות שולף את כל ההקלטות החדשות מ-Twilio, מתאים כל הקלטה לליד לפי טלפון, מתמלל דרך ivrit.ai (RunPod), מעלה את התמלול ל-Airtable, מריץ ניתוח דרך Claude, ויוצר טיוטת מייל ב-Gmail עם קישור ישיר לטיוטה בעמודת Airtable.

## מבנה התיקייה

```
שיחות מכירה אוטומציה/
├── .env                      # מפתחות API (לא להעלות לגיטהאב!)
├── .env.example              # תבנית
├── .gitignore
├── config.json               # הגדרות (Airtable field IDs, chunking, models)
├── requirements.txt
├── run_pipeline.sh           # עטיפת bash להפעלה
├── sales_pipeline.py         # האורקסטרטור המרכזי
├── README.md
├── modules/
│   ├── airtable_client.py    # CRUD + התאמה לפי טלפון
│   ├── calendly_sync.py      # Pipeline A
│   ├── transcribe.py         # ivrit.ai דרך RunPod + chunking
│   ├── twilio_sync.py        # Pipeline B (מתזמר הכל)
│   ├── analyze.py            # Claude — ניתוח שיחה וחיבור מייל
│   └── email_draft.py        # Gmail API drafts.create
├── prompts/
│   ├── analysis.txt          # פרומפט ניתוח שיחה
│   └── email_draft.txt       # פרומפט כתיבת מייל
├── state/                    # מצב מקומי (לא נדרש כרגע — הכל ב-Airtable)
└── logs/                     # לוגי הרצה
```

## התקנה במק (מה שלהבת צריכה לעשות)

### דרישות קדם

1. Python 3.10+ (`python3 --version`)
2. ffmpeg (`brew install ffmpeg`)

### שלב 1 — העברת התיקייה מחוץ ל-iCloud

הקוד חייב לשבת **מחוץ ל-iCloud** (iCloud מוחק קבצים). בטרמינל:

```bash
mkdir -p ~/Applications
cp -R "/path/to/שיחות מכירה אוטומציה" ~/Applications/sales-automation
cd ~/Applications/sales-automation
```

(אפשר גם להשאיר את הנתיב בעברית — פשוט לא בתוך Documents/iCloud.)

### שלב 2 — התקנת התלויות

```bash
cd ~/Applications/sales-automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### שלב 3 — הגדרת Gmail OAuth (פעם אחת)

Gmail API דורש OAuth credentials. שלהבת צריכה:

1. להיכנס ל-[Google Cloud Console](https://console.cloud.google.com/)
2. ליצור פרויקט חדש (או להשתמש בקיים)
3. להפעיל **Gmail API** ב-"APIs & Services" → "Library"
4. ב-"APIs & Services" → "OAuth consent screen":
   - User Type: External
   - App name: שיחות מכירה אוטומציה
   - Scopes: `https://www.googleapis.com/auth/gmail.compose` ו-`.../gmail.modify`
   - Test users: להוסיף את shalhevet@aimprove.co.il
5. ב-"APIs & Services" → "Credentials":
   - יצירת "OAuth client ID" → Application type: **Desktop app**
   - הורדת קובץ ה-JSON ושמירתו בתיקיית הפרויקט בשם `credentials.json`

בהרצה הראשונה ייפתח דפדפן שיבקש אישור — אחרי אישור ייווצר `token.json` ולא צריך יותר.

### שלב 4 — בדיקת ההרצה הראשונה

```bash
cd ~/Applications/sales-automation
source venv/bin/activate
python3 sales_pipeline.py
```

אם הכל תקין תראי:
- Pipeline A מדפיס: `Calendly: found N events`
- Pipeline B מדפיס: `Twilio: found N recordings in last 24 hours`
- ב-Airtable מופיעים לידים חדשים + (אם יש הקלטות) תמלולים ותובנות.

### שלב 5 — הגדרת cron (הפעלה אוטומטית כל 5 דקות)

```bash
crontab -e
```

והוסיפי את השורה הבאה (שני את הנתיב לפי הצורך):

```cron
*/5 * * * * /bin/bash -l -c 'cd ~/Applications/sales-automation && ./run_pipeline.sh' >> ~/Applications/sales-automation/logs/cron.log 2>&1
```

**חשוב:** אם cron לא מוצא ffmpeg או python, ייתכן שצריך לתת לו Full Disk Access ולהוסיף נתיבי PATH ב-`run_pipeline.sh`.

## ניטור ותחזוקה

### איך לוודא שרץ

```bash
# האם הלוג מתעדכן?
tail -f ~/Applications/sales-automation/logs/pipeline_$(date +%Y-%m).log

# האם cron רץ?
crontab -l
```

### מה לבדוק כשמשהו לא עובד

1. **אין לידים חדשים מ-Calendly** — בדקי שה-Calendly token לא פג (ה-JWT שלו תקף שנה).
2. **אין תמלולים** — בדקי ב-RunPod dashboard שה-endpoint פעיל.
3. **אין טיוטות ב-Gmail** — ודאי ש-`token.json` קיים ולא פג.
4. **טיוטה נוצרת אבל מוזרה** — ערכי את `prompts/email_draft.txt` — זה הפרומפט הישיר שמחבר את המייל.

### עדכון פרומפט

לא צריך להפעיל מחדש שום דבר — פשוט ערכי את הקובץ ב-`prompts/` וההרצה הבאה תשתמש בו.

## טיפים למקרים נדירים

### ליד בלי מייל ב-Calendly
הפייפליין ייצור רשומה, יתמלל, ויציב סטטוס "טיוטה מוכנה" — אבל בלי לינק ל-Gmail. תוכלי להוסיף מייל ידנית ואז להריץ שוב את הסקריפט (הוא ידע לדלג על המקומות שכבר בוצעו).

### ליד טלפוני בלי התאמה ב-Calendly
הפייפליין ייצור רשומת "ליד ללא התאמה" עם הטלפון — תוכלי לעדכן את השם והמייל ידנית.

### שיחה ארוכה מ-15 דקות
הקובץ יחולק אוטומטית ל-chunks של ~15 דקות (917 שניות) והתמלולים יאוחדו.

## אבטחה

- `.env` מכיל את כל המפתחות — **אל תעלי אותו לגיטהאב**. הוא כבר ב-`.gitignore`.
- `credentials.json` ו-`token.json` גם הם ב-`.gitignore`.
- כל המפתחות ניתנים לריסט דרך הפלטפורמות המתאימות אם נגנבים.

## מקורות הקוד

- דפוסי ivrit.ai/RunPod משוכפלים מ-`~/Applications/zoom-workflow/zoom_pipeline.py` (הוכחו בייצור)
- Claude model: `claude-opus-4-6` (ניתן לשנות ב-`config.json`)
