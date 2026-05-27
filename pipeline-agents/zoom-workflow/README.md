# סיכום פגישות זום אוטומטי

## מה זה עושה
כל פעם שיש הקלטת זום חדשה — המערכת מזהה אותה, מתמללת, מנתבת לפי סוג הפגישה (שיחת מכירה, שיעור, פגישה פנימית...), ומייצרת פלט ייעודי שנשמר ב-Notion.

## למה זה שימושי
במקום להאזין מחדש לפגישה שלמה או לכתוב סיכום ידני — יש לך סיכום אוטומטי שמותאם לסוג הפגישה. פגישת מכירה מקבלת ניתוח פסיכולוגי של הלקוח, שיעור מקבל מסמך ידע עשיר, פגישה פנימית מקבלת action items.

## מה צריך
- [ ] Python 3.10+
- [ ] ffmpeg מותקן (`brew install ffmpeg`)
- [ ] חשבון RunPod + endpoint של ivrit.ai (לתמלול עברית)
- [ ] מפתח OpenAI API (לניתוב ולעיבוד)
- [ ] Notion Integration Token + Database ID
- [ ] תיקיית הקלטות זום (`~/Documents/Zoom`)

## איך מריצים

### התקנה
```bash
pip3 install openai requests python-dotenv
cp .env.example .env
# ערכו את .env עם המפתחות שלכם
```

### הרצה אוטומטית (ברקע)
```bash
chmod +x bash_watcher.command bash_watcher_daemon.sh
./bash_watcher.command
```
המערכת סורקת כל 60 שניות ומעבדת הקלטות חדשות.

### הרצה ידנית (קובץ בודד)
```bash
python3 zoom_pipeline.py --file path/to/recording.m4a --folder-name "שם הפגישה"
```

## איך להתאים אישית

### סוגי פגישות (ניתוב)
ערכו את `prompts/routing.txt` כדי להגדיר את סוגי הפגישות שלכם. ברירת המחדל:
- שיחת מכירה
- פגישת הטמעה
- פגישה פנימית
- שיעור (3 סוגי חילוץ)
- אפיון ארגוני
- כללי

### פרומפטים ייעודיים
כל סוג פגישה מקבל פרומפט משלו בתיקיית `prompts/`. ערכו אותם או הוסיפו חדשים.

### Notion Database
צרו דאטהבייס ב-Notion עם העמודות:
- שם הקלטה (title)
- מסלולים (multi_select)
- קטגוריה (select)
- סטטוס (select: הצלחה / שגיאה / לבדיקה ידנית)
- תאריך הקלטה (date)
- נתיב קובץ (rich_text)
- סיבת שגיאה (rich_text)

עדכנו את `config.json` עם ה-Database ID שלכם.

## מבנה הקבצים
```
zoom-workflow/
├── bash_watcher.command      ← הפעלה (דאבל-קליק)
├── bash_watcher_daemon.sh    ← הסורק שרץ ברקע
├── zoom_pipeline.py          ← הלוגיקה: תמלול → ניתוב → עיבוד → שמירה
├── config.json               ← הגדרות (DB ID, מודל, נתיבים)
├── prompts/                  ← פרומפטים לפי סוג פגישה
│   ├── routing.txt           ← פרומפט ניתוב
│   ├── implementation.txt    ← פגישת הטמעה
│   ├── internal.txt          ← פגישה פנימית
│   ├── org_sales.txt         ← שיחת מכירה
│   └── ...
├── .env.example              ← תבנית למפתחות API
└── .gitignore
```
