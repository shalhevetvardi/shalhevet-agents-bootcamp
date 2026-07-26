# נחמיה — מנהל העבודה 🧱

**המודל הכי חזק שלך לא אמור להחזיק את הפטיש.**

נחמיה הופך את המודל החזק בשיחה למנהל עבודה: הוא מתכנן, מחלק כרטיסי עבודה
מוגדרים-היטב לעובדים זולים (Sonnet למימוש, Haiku לסיור), ולא מקבל שינוי
משמעותי עד שמאמת "עיוור" — סוכן טרי שלא ראה איך העבודה נעשתה — משחזר את
הראיות בעצמו.

התוצאה: איכות של המודל החזק, במחיר של המודלים הזולים.

## התקנה

**Claude Code (מומלץ — המצב המלא):**

```
/plugin marketplace add <repo-שלך>
/plugin install nehemiah-foreman@nehemiah-foreman
```

או ידנית (מבנה ה-ZIP של ספריית הסקילים): העתיקו את התיקייה `nehemiah-foreman`
כולה לתוך `~/.claude/skills/`, ואת שלושת הקבצים שבתת-התיקייה `agents/` לתוך
`~/.claude/agents/`:

```
cp -r nehemiah-foreman ~/.claude/skills/ && cp nehemiah-foreman/agents/*.md ~/.claude/agents/
```

> שימו לב: קובצי ה-agents נטענים רק באתחול סשן. אחרי התקנה ידנית —
> פתחו שיחה חדשה כדי שטיפוסי `nehemiah-*` ייטענו. בסשן שבו הותקנו,
> נחמיה יפעל לפי נוהל ה-fallback שב-`references/routing.md`.

**Claude.ai / Desktop:** העלו את `nehemiah-foreman-skill.zip` תחת
הגדרות ← Capabilities ← Skills (נדרש code execution מופעל). שם נחמיה רץ
ב"מצב משמעת" — אין סוכני-משנה, אז הוא מפריד תכנון מביצוע מביקורת עצמית,
ואומר בכנות שביקורת עצמית אינה אימות עיוור.

**מומלץ:** הוסיפו שורה ל-CLAUDE.md כדי שהסקיל יופעל באמינות:

```
לכל משימה מרובת-קבצים או מרובת-שלבים — הפעל את הסקיל nehemiah-foreman.
```

## מה בפנים

| קובץ | תפקיד |
|---|---|
| `skills/nehemiah-foreman/SKILL.md` | הליבה: חוקים, מצבים, שער האצלה |
| `references/routing.md` | תרגום דרגות למודלים חיים + ניתוב משימות תוכן |
| `references/delegation.md` | תבנית הכרטיס, סטטוסים, סולם אסקלציה, יומן |
| `references/verification.md` | שתי שכבות אימות + כללי הכרעה |
| `agents/nehemiah-worker.md` | סוס העבודה (Sonnet) |
| `agents/nehemiah-verifier.md` | המאמת העיוור (יורש את מודל השיחה) |
| `agents/nehemiah-scout.md` | הרץ (Haiku) |

## קרדיט

בהשראת [fable-foreman](https://github.com/olsenbrands/fable-foreman)
מאת Jordan Olsen (MIT). גרסה זו: עברית, Claude בלבד (ללא Codex),
ומורחבת למשימות תוכן — לא רק קוד.

MIT © Aimprove
