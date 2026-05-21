# יצירת B-Roll מתסריט — תמונות AI וקליפי וידאו

## מה זה עושה
נותנים תסריט של ריל (או טקסט כלשהו) → המערכת מייצרת storyboard מפורט → תמונות AI לכל פאנל → קליפי וידאו קצרים מהתמונות. בסוף יש לכם חבילה מלאה של B-Roll מוכנה לעריכה.

## למה זה שימושי
במקום לחפש stock footage או לצלם — מייצרים ויזואל מותאם לתוכן שלכם ב-AI. מתאים לרילסים, פרזנטציות, או כל תוכן ויזואלי.

## מה צריך
- [ ] Python 3.10+
- [ ] מפתח Anthropic API (ליצירת storyboard)
- [ ] חשבון fal.ai + FAL_KEY (ליצירת תמונות ב-Flux וסרטונים ב-Kling)
- [ ] קובץ "מוח יצירתי" — prompt file שמגדיר את הסגנון (ראו `b-roll-prompter/`)

## איך מריצים

### התקנה
```bash
cd pipeline
pip3 install -r requirements.txt
cd ..
cp .env.example .env
# ערכו את .env עם המפתחות שלכם
```

### הזרימה

```
תסריט ריל (input/)
       ↓
[1] generate_storyboard.py  → storyboard.md (פאנלים + פרומפטים)
       ↓
[2] generate_images.py      → images/ (תמונת PNG לכל פאנל)
       ↓
[3] generate_video.py       → videos/ (קליפ MP4 לכל פאנל)
       ↓
[4] generate_shot_list.py   → shot-list.md (מפת עריכה)
```

### הרצה ידנית (שלב אחרי שלב)
```bash
# יצירת storyboard מתסריט
python3 pipeline/generate_storyboard.py --from-teaser input/my-script.md

# יצירת תמונות מ-storyboard
python3 pipeline/generate_images.py output/my-project/storyboard.md output/my-project/images/

# יצירת וידאו מתמונות
python3 pipeline/generate_video.py output/my-project/storyboard.md output/my-project/images/ output/my-project/videos/

# יצירת shot list
python3 pipeline/generate_shot_list.py output/my-project/storyboard.md output/my-project/images/ output/my-project/videos/
```

## איך להתאים אישית

### הסגנון הויזואלי
ערכו את `knowledge/visual-style-guide.md` — שם מוגדרים:
- פלטת צבעים
- סגנון תאורה
- כללי קומפוזיציה
- תיאור דמות קבועה (character sheet)
- תיאור מקום קבוע (location sheet)

### המוח היצירתי
הקובץ `b-roll-prompter/b-roll-prompter.md` הוא ה-system prompt שמנחה את Claude איך ליצור storyboards. ערכו אותו כדי לשנות את סגנון התוצרים.

### פורמולות הפרומפטים
`knowledge/prompt-formulas.md` מכיל דוגמאות וכללים לכתיבת פרומפטים טובים ל-Flux ול-Kling/Veo.

## עלויות משוערות
- **תמונות (Flux Pro via fal.ai):** ~$0.04-0.05 לתמונה
- **וידאו (Kling 3.0 Pro via fal.ai):** ~$0.15 לקליפ 5 שניות
- **Storyboard (Claude):** ~$0.05-0.10 לסטוריבורד

לריל אחד (10 פאנלים): ~$2-3 סה"כ

## מבנה הקבצים
```
b-roll-generator/
├── pipeline/
│   ├── generate_storyboard.py   ← שלב 1: תסריט → storyboard
│   ├── generate_images.py       ← שלב 2: storyboard → תמונות
│   ├── generate_video.py        ← שלב 3: תמונות → קליפים
│   ├── generate_shot_list.py    ← שלב 4: מפת עריכה
│   └── requirements.txt
├── knowledge/
│   ├── visual-style-guide.md    ← הגדרת סגנון ויזואלי
│   └── prompt-formulas.md       ← נוסחאות לפרומפטים טובים
├── b-roll-prompter/
│   └── b-roll-prompter.md       ← "המוח" — system prompt ליצירתיות
├── input/                       ← שימו כאן תסריטים
├── output/                      ← תוצרים נוצרים כאן
├── examples/                    ← דוגמה לפלט מוגמר
└── .env.example
```
