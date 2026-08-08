# HANDOFF / STATE - rebuild-plugin (סקיל התלמידים)

**עודכן:** 08-08-2026 | **גרסה חיה:** v0.4.2 | **ריפו:** `shalhevet-agents-bootcamp`

מסמך זה מתעד את מצב סקיל ה-rebuild של תלמידי הטירונות, כדי שאפשר להמשיך ממנו בכל חשבון/מחשב. הוא עצמאי - הכל כאן.

---

## מה זה
`rebuild-plugin` = סקיל שתלמידי טירונות מתקינים, שאורז מחדש את הסוכן שלהם לקובץ `.plugin`, **מתקין אותו אוטומטית ומחליף את הגרסה הישנה**. חי ב-`skills/rebuild-plugin/` בריפו הזה, ומופץ לתלמידים דרך קישור הורדה מ-GitHub.

## הגרסה החיה: v0.4.2 (08-08-2026)
- **מה היא עושה:** אריזה + התקנה אוטומטית + החלפת הישן, **בבטחה**: גיבוי לפני החלפה, אימות אחרי, שחזור-אוטומטי בכישלון (ואז נפילה לידני), 4 בדיקות מבנה לפני אריזה (שורש הפלאגין, מיקום SKILL.md, BOM, סכמת plugin.json), **רישום מלא** של 3 קבצי הרישום (installed_plugins + marketplace.json + enabledPlugins) כך שהפלאגין באמת עולה, אריזת Windows דרך `System.IO.Compression` (לא `Compress-Archive`), `robocopy` לפלאגינים כבדים, דילוג בחן אם אין תיקיית Claude Desktop.
- **מבוססת** על הגרסה של התלמיד **משה** (kontakt@drehpunkt-ab.com), שנבדקה על **Windows 11 אמיתי**.
- **commit:** `0195d6f` על `main` (נדחף ואומת חי).
- **קישור ההורדה (מה שהתלמידים מקבלים):**
  `https://github.com/shalhevetvardi/shalhevet-agents-bootcamp/raw/main/skills/rebuild-plugin.zip`
- **מייל broadcast** "ה-rebuild תוקן - התקינו את הגרסה המעודכנת" נשלח/מוכן ל-45 תלמידים פעילים (דרך סקיל `kaas:broadcast`).

## הסאגה (איך הגענו ל-v0.4.0)
1. **v0.2.0 (03/08)** - הוסיף auto-install; **שבר תלמידי Windows**: PowerShell `Out-File` הוסיף BOM לקבצי הרישום ← מנתח ה-JSON נפל ← כל הפלאגינים המותקנים נעלמו בשקט.
2. **v0.3.0 (05/08)** - נסיגה: ירד ל-**התקנה ידנית בטוחה** (הסקיל לא כותב לקבצים הפנימיים), כדי לעצור את הדימום.
3. **v0.4.0 (07/08)** - הפתרון האופטימלי: משה שלח SKILL.md שעושה auto-install **בבטחה** (הבאג של ה-BOM תוקן + רשת ביטחון: גיבוי/אימות/שחזור). אומץ ושוחרר.
4. **v0.4.1 (08/08)** - התלמידה **ליטל** בדקה על כל 24 הסוכנים שלה (Windows) ומצאה שההתקנה מתקינה קבצים אבל **לא רושמת את הפלאגין עד הסוף** (חסרו `marketplace.json` ו-`enabledPlugins`, אז הפלאגין נראה מותקן ולא עלה). תוקן: רישום מלא של 3 קבצי הרישום + אימות 4-מישורים + בדיקת סכמת plugin.json + תיקון נתיב-ארוך ב-Windows.
5. **v0.4.2 (08/08)** - ליטל אישרה ש-v0.4.1 עובד (הסוכנים עולים), ומצאה נקודה מינורית: האורז כלל קבצי `.plugin`/`.zip` ישנים מתיקיית הסוכן. תוקן: החרגת `*.plugin`/`*.zip` באריזה. (נקודת ה"נייד / חלון Plugins" נדחתה - לא רלוונטית לתלמידים שעובדים ב-Claude Code.)

## קבצים (נתיבים מלאים)
- `skills/rebuild-plugin/SKILL.md` - הלוגיקה (v0.4.2). **מקור-האמת - עורכים כאן.**
- `skills/rebuild-plugin/.claude-plugin/plugin.json` - version 0.4.2.
- `skills/rebuild-plugin/README.md` - הסבר לתלמיד.
- `skills/rebuild-plugin.zip` - חבילת ההפצה (מה שהקישור מגיש). מכיל את התיקייה `rebuild-plugin/` עם 3 הקבצים.

## אם צריך להמשיך לתקן (v0.4.1+)
1. לערוך את `skills/rebuild-plugin/SKILL.md` (המקור).
2. להעלות את `version` ב-`skills/rebuild-plugin/.claude-plugin/plugin.json`.
3. **לבנות מחדש את ה-zip** (חובה, אחרת הקישור מגיש גרסה ישנה):
   `cd skills && zip -rq rebuild-plugin.zip rebuild-plugin -x '*.DS_Store'`
4. לאמת: אין BOM ב-plugin.json (`od -An -tx1 -N3 <plugin.json>` צריך `7b ...`, לא `ef bb bf`), JSON תקין, וה-zip מכיל את המבנה `rebuild-plugin/`.
5. commit ממוקד עם **pathspec מפורש** (לא `git add -A`) + `git push`. הקישור מגיש מ-`main` מיד.
6. אם משנים התנהגות מהותית - מייל broadcast לתלמידים (סקיל `kaas:broadcast`, ל-45 הפעילים).

## כללי בטיחות (למה להיזהר - 4 מלכודות שבירה-בשקט)
1. **רישום מלא = 4 מישורים** (v0.4.1). פלאגין עולה רק אם: (א) הקבצים בתיקייה, (ב) רשומה ב-`marketplace.json`, (ג) רשומה ב-`installed_plugins.json`, (ד) `enabledPlugins: true` ב-`settings.json`. כתיבה לכולם - רק בבטחה: בלי BOM, קריאה-קודם + שימור רשומות, גיבוי+אימות+שחזור, דילוג אם אין Claude Desktop. (v0.4.0 פספס ב+ד ← הפלאגין נראה מותקן ולא עלה.)
2. **BOM = רוצח JSON שקט** (PowerShell `Out-File` מוסיף אותו).
3. **Windows: `System.IO.Compression`, לא `Compress-Archive`** (backslash שובר התקנה).
4. **`SKILL.md` תמיד ב-`skills/<שם>/SKILL.md`** (בשורש = הסוכן לא מופיע, בלי שגיאה).

## תיעוד ב-VO (Virtual Office)
- ישות סקיל: «rebuild-plugin (סקיל תלמידים)» (מחלקת KaaS) - עם ADR מלא של הסאגה ב-history.
- כלל: «kaas-plugin-packaging-safety» (מחלקת KaaS) - 4 המלכודות.

## אסור לגעת
- **עבודת המחזורים** (Cohort/backfill) - של הסשן "אנה", לא קשור לזה.
- **הפלאגין הפנימי של KaaS** ב-Storyteling - הוחלט מפורשות לא לערוך (המלכודות לא נוגעות בו).

## הקשר סשן (דברים אחרים שקרו 06-07/08, לא חלק מה-rebuild)
- CLAUDE.md / Starter Rules של הטירונות - עברו התאמה גנרית לכל מערכת הפעלה (חי בנושן + בריפו).
- באג טירגוט המחזורים בברודקאסט - הועבר לטיפול הסשן "אנה".
