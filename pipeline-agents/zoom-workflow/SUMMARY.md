# סיכום פעולות — Zoom Workflow
## עדכון אחרון: 3 מרץ 2026

---

## מה קרה?
האוטומציה של תמלול הקלטות זום הפסיקה לעבוד במחשב shalhevet.

## מה מצאנו?
1. **Python watcher (zoom_watcher.py) קרס** — בגלל בעיית הרשאות TCC (macOS לא נותן ל-Python גישה לתיקיית Documents)
2. **שגיאת "Too many open files"** — watchdog ב-Python ניסה לעקוב אחרי 300+ תיקיות ונכשל
3. **Login Items הפעילו את הגרסה הישנה** — ZoomWatcher (Python) רץ במקום bash_watcher
4. **פקודת `timeout` לא קיימת ב-macOS** — הדימון החדש (v3) קרס כי timeout זה פקודת Linux בלבד

## מה תיקנו?
1. **עברנו מ-Python ל-bash watcher** — bash_watcher_daemon.sh סורק כל 60 שניות עם `find`
2. **הסרנו ZoomWatcher מ-Login Items** — רק bash_watcher.command נשאר
3. **הפעלנו מצב רקע** — הדימון רץ עם nohup/disown, בלי Terminal פתוח
4. **נתנו Full Disk Access ל-/bin/bash** — כך הדימון יכול לגשת לתיקיית Documents
5. **החלפנו timeout במנגנון macOS תואם** — background process + kill timer
6. **ביטלנו את start_watcher.command** — שונה ל-.DISABLED למניעת הפעלה בטעות
7. **הוספנו שמירת כישלונות לנוטיון** — גם אם הקלטה נכשלת, נוצרת שורה בנוטיון עם סטטוס "שגיאה" + הסבר
8. **עדכנו את עמוד התיעוד בנוטיון** — מדריך פתרון בעיות, הוראות לקלוד, עיצוב עם טוגלים

## מה עובד עכשיו?
- ✅ דימון bash רץ ברקע (בלי Terminal)
- ✅ סורק הקלטות חדשות כל 60 שניות
- ✅ תומך בקבצי .m4a, .mp3, .M4A, .MP3
- ✅ תומך בהקלטות בתת-תיקיות וגם ישירות ב-root של Zoom
- ✅ עולה אוטומטית עם הפעלת המחשב (Login Items)
- ✅ עובד בלי Terminal פתוח
- ✅ שומר שורת כישלון בנוטיון כשעיבוד נכשל (עם סיבת השגיאה)

## הקלטות שעובדו ב-3 מרץ:
1. ✅ פגישה עם בן עקיבא — מעבר על שיעור 2 בקורס אמדוקס
2. ✅ פגישה פנימית עם בן — לקראת המשך הכשרות בארגונים
3. ✅ 0227.MP3
4. ✅ צ׳קפוינט עם סיון מאמדוקס — לקראת המשך ההכשרות

## קבצים שהשתנו:
| קובץ | מה השתנה |
|-------|----------|
| `bash_watcher.command` | לונצ'ר חדש — מפעיל דימון ברקע |
| `bash_watcher_daemon.sh` | דימון חדש — סריקה עם find, timeout תואם macOS |
| `start_watcher.command.DISABLED` | בוטל — היה מפעיל Python watcher |
| `zoom_pipeline.py` | הוספת פונקציה `save_failure_to_notion()` — שומרת שורת כישלון בנוטיון |

## סטטוס כישלונות בנוטיון:
כשהפייפליין נכשל, נוצרת שורה בטבלת "תמלולים" עם:
- **סטטוס:** "שגיאה" (אדום)
- **סיבת שגיאה:** הסבר מפורט, למשל:
  - `[תמלול נכשל] Whisper לא הצליח לתמלל את הקובץ`
  - `[ניתוב נכשל] GPT לא הצליח לנתב את ההקלטה למסלול`
  - `[שגיאה כללית] ...` + פירוט טכני

## נתיבים חשובים:
| מה | נתיב |
|----|------|
| תיקיית הקוד | `~/Applications/zoom-workflow/` |
| הקלטות זום | `/Users/shalhevet/Documents/Zoom` |
| לונצ'ר | `~/Applications/zoom-workflow/bash_watcher.command` |
| דימון | `~/Applications/zoom-workflow/bash_watcher_daemon.sh` |
| פייפליין | `~/Applications/zoom-workflow/zoom_pipeline.py` |
| לוג | `~/Applications/zoom-workflow/watcher.log` |
| שגיאות | `~/Applications/zoom-workflow/watcher_stderr.log` |
| הגדרות | `~/Applications/zoom-workflow/config.json` |
| קבצים שעובדו | `~/Applications/zoom-workflow/processed_files.json` |
| Notion DB תמלולים | `ed135505c9144b2c86ff49ed3c767af0` |
| Notion עמוד תיעוד | `31113b4c-3d78-8139-80bd-caa1a88730a6` |
