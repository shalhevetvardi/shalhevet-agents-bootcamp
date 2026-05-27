# מענה אוטומטי למיילים עם AI

## מה זה עושה
שולף מיילים מתווית מסוימת ב-Gmail, שולח אותם ל-Claude (Batch API), מקבל תגובות אישיות מותאמות, ויוצר טיוטות reply ב-Gmail. אתם רק בודקים ושולחים.

## למה זה שימושי
כשיש 50+ מיילים שמחכים לתגובה — במקום לכתוב כל אחד ידנית, ה-AI כותב תגובות אישיות בטון שלכם, עם התאמה למה שהאדם שאל. אתם רק עוברים על הטיוטות ושולחים.

## מה צריך
- [ ] Python 3.10+
- [ ] מפתח Anthropic API
- [ ] Gmail OAuth2 credentials (Client ID, Secret, Refresh Token)
- [ ] תווית ב-Gmail (ברירת מחדל: "VIP")
- [ ] קובץ הוראות מותאם לעסק שלכם

## איך מריצים

### התקנה
```bash
cd scripts
pip3 install -r requirements.txt
cd ..
cp .env.example .env
# ערכו את .env עם המפתחות שלכם
```

### התאמה
1. ערכו את `instructions.md` — הוראות ה-AI (טון, קטגוריות, מבנה תגובה)
2. ערכו את `guides-catalog.md` — רשימת מדריכים/תכנים שאפשר להציע

### הרצה
```bash
# הרצה מלאה — שליפה מ-Gmail → עיבוד → יצירת טיוטות
python3 scripts/run_reply_agent.py

# בדיקה (בלי ליצור טיוטות)
python3 scripts/run_reply_agent.py --dry-run

# רק 5 מיילים (לבדיקה)
python3 scripts/run_reply_agent.py --limit 5

# שליחת כל הטיוטות שנוצרו
python3 scripts/run_reply_agent.py --send-drafts
```

## איך להתאים אישית

### הטון
ערכו `instructions.md` — שם מוגדר:
- מי אתם ואיך אתם מדברים
- קטגוריות התגובה (רגיל, עם-מדריך, הפניה...)
- מבנה התגובה (פתיחה, גוף, סיום)
- חוקים (מה מותר ומה אסור)

### המודל
ברירת מחדל: Claude Opus. שנו את `MODEL` בראש הסקריפט אם רוצים משהו אחר.

### הפילטר
ברירת מחדל: תווית "VIP". שנו את ה-query ב-`fetch_vip_emails` לכל פילטר אחר (subject, sender, label).

### העלות
הסקריפט משתמש ב-Batch API (50% הנחה) + Prompt Caching (90% הנחה על חלק מה-tokens). עלות טיפוסית: ~$0.01-0.05 למייל.

## מבנה הקבצים
```
email-auto-responder/
├── scripts/
│   ├── run_reply_agent.py   ← הסקריפט הראשי
│   └── requirements.txt
├── instructions.md          ← הוראות לAI (התאימו!)
├── guides-catalog.md        ← קטלוג תכנים להצעה
├── .env.example
└── .gitignore
```

## הזרימה
```
[1] שליפת מיילים מ-Gmail (לפי תווית/פילטר)
       ↓
[2] קיבוץ לפי שרשור (thread)
       ↓
[3] שליחה ל-Claude Batch API (עם prompt caching)
       ↓
[4] פרסור תשובות + יצירת טיוטות reply ב-Gmail
       ↓
[5] אתם בודקים ושולחים (--send-drafts)
```
