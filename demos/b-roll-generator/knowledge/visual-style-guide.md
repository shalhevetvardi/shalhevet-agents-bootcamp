# 🎨 Visual Style Guide — סגנון Sofia Coppola לאימפרוב

> **הסוכן AI יקרא את הקובץ הזה לפני יצירת storyboard, פרומפטים לתמונות, או פרומפטים לוידאו.**

---

## 🌟 הסגנון הכללי

**שם הסגנון:** Cinematic Coppola Soft

**השראה:**
- צילומי Sofia Coppola: *Lost in Translation*, *The Virgin Suicides*, *Marie Antoinette*
- צילומי פורטרט של Autumn de Wilde
- מגזיני lifestyle כמו *Kinfolk* ו-*Cereal* (טאצ' מינימליסטי)

**מהות הסגנון:**
- **רך, לא חד**
- **אינטימי, לא דרמטי**
- **ניאו-ריאליסטי, לא היפר-ריאליסטי**
- **memory-film vibe** — כאילו הצילום הוא זיכרון, לא רגע הווה

---

## 🎨 פלטת הצבעים

### צבעים דומיננטיים:
- **אפרסק מאובק** (Dusty peach) — `#E8B5A0`
- **קרם בז'** (Cream beige) — `#E8DCC4`
- **לבן-שמנת** (Soft white / cream white) — `#F5EFE6`
- **חום עץ חם** (Warm wood) — `#A88B6F`

### אקסנטים:
- **בורדו עמוק** (Deep burgundy) — `#6B2C2C` ← לטיפוגרפיה דרמטית
- **זהב עדין** (Subtle gold) — `#C9A876` ← לתכשיטים, לפרטים קטנים
- **אפור-כהה** (Dark gray) — `#4A4540` ← לטקסט נורמלי

### מה להימנע:
- ❌ כחול-קר טכנולוגי (אלא אם זה מסך טלפון בלילה)
- ❌ ניאון, פלורסנט
- ❌ צבעים רוויים מאוד (saturation גבוה)
- ❌ שחור עמוק (אלא בלילה)

---

## ☀️ תאורה

### עקרונות:
1. **תאורה טבעית** בלבד (לא סטודיו)
2. **שעת הזהב** (Golden hour) — בוקר מוקדם או שעת אחר צהריים
3. **אור רך מסונן** — דרך וילון פשתן, דרך עץ, דרך זכוכית
4. **Rim light** — אור מאחור שיוצר הילה עדינה על השיער/כתפיים

### תאורה לפי סוג סצנה:

| סצנה | תאורה |
|------|--------|
| בוקר אינטימי | אור זהוב רך משמאל, מסונן דרך וילון |
| אחר צהריים מאוחר | אור חמים נמוך, צללים ארוכים, פלטה כתומה |
| לילה | אור יחיד דומיננטי (מנורת שולחן זהובה או מסך טלפון) |
| חוץ | מעונן רך — לא שמש ישירה |

### מילות מפתח לפרומפט:
- "soft natural light"
- "golden hour"
- "filtered through sheer curtains"
- "warm window light"
- "gentle rim light"
- "diffused morning sun"

---

## 📷 קומפוזיציה

### עקרונות:
1. **Breathing compositions** — הרבה "אוויר" סביב הסובייקט
2. **Rule of thirds + space** — לא ממקמים את הסובייקט במרכז המוחלט
3. **Negative space** — מרחב שלילי נדיב מצד אחד של הפריים
4. **Shallow depth of field** — רקע מטושטש (bokeh)

### זוויות מומלצות:
- **Eye level** — לרוב הסצנות. נותן אינטימיות.
- **Slightly low angle** — כשרוצים לתת לדמות כבוד או שקט
- **Top-down 45°** — לסצנות שולחן, חפצים
- **POV (over the shoulder)** — לסצנות של שימוש בטלפון
- **Medium shot** (מותניים ומעלה) — הכי שכיח אצל קופולה

---

### 🎯 איך לתאר זווית מצלמה (חובה לקרוא)

> מודלי תמונה לא מבינים שפה קולנועית. הם מבינים אילוצים גיאומטריים.

**הכלל:** במקום שם של זווית, תאר **איפה המצלמה ומה רואים/לא רואים**.

#### דוגמה — Over-the-Shoulder

❌ **לא עובד:**
> "POV over-the-shoulder angle of the woman holding her phone"

הסיבה: המודל מתרגם "OTS" ל"בן אדם + מסך = שניהם ברורים" → יוצא שוט פרונטלי.

✅ **עובד:**
> "Camera positioned behind the woman, slightly above shoulder level, looking forward toward the phone screen. Back of head visible. Shoulder and part of upper back in foreground. No full face visible — at most a small partial profile at the edge of frame. Phone screen in sharp focus, slightly angled."

#### דוגמה — Medium Shot של דמות

❌ **לא עובד:**
> "Medium shot of an Israeli woman with brown eyes"

הסיבה: "medium shot" לבד עמום. המודל יבחר חיתוך.

✅ **עובד:**
> "The woman is framed from the chest up, centered slightly to the left of frame. Camera at her eye level, approximately 1.5 meters away. Her face fully visible, looking three-quarter toward the camera but eyes drifting off-frame to the right."

#### דוגמה — Close-up של חפץ

❌ **לא עובד:**
> "Macro close-up of a phone on a desk"

✅ **עובד:**
> "Camera positioned 30cm above the desk surface, lens pointing straight down at a 30-degree angle. Phone fills 70% of the frame, screen sharp and readable. Wooden desk surface visible around the phone, slightly out of focus. No people in frame."

---

### 🎯 כללי מסגרת לכתיבת זווית מצלמה

לכל פאנל, ענה על 5 שאלות לפני כתיבת הפרומפט:

1. **מיקום מצלמה** — מאיפה היא מסתכלת? (מאחור / מהצד / מלמעלה / בגובה עיניים)
2. **מה רואים** — חלקים ספציפיים בלבד (גב, חצי פרופיל, יד, חפץ)
3. **מה לא רואים** — איסורים מפורשים (no full face, no hands, no background people)
4. **מי בפוקוס** — איזה אלמנט חד, איזה מטושטש
5. **מי ב-foreground** — מה תופס את החזית

> בלי תשובה מפורשת ל-3 — המודל יברח לקומפוזיציה הסטנדרטית שלו (פרונטלי, נקי, סימטרי).

### 🎯 כל אלמנט שמוזכר חייב להיות בקאדר

**הבעיה:** אם הזכרת בפרומפט "עיניים חומות מהורהרות" בשוט מהגב — המודל מקבל הוראה סותרת ויעוות.

**הכלל:** תאר רק את מה שיהיה גלוי בתמונה הסופית.

- שוט מהגב → לא מזכירים פנים, עיניים, איפור
- שוט close-up של ידיים → לא מזכירים שיער, פנים, שמלה
- shot של חפץ → לא מזכירים את הדמות בכלל

### זוויות להימנע:
- ❌ Dutch angle (זווית אלכסונית) — דרמטי מדי
- ❌ Extreme low angle — אגרסיבי
- ❌ Bird's eye מאוד גבוה — מנותק

### מילות מפתח לפרומפט:
- "shallow depth of field"
- "soft bokeh background"
- "eye level"
- "medium shot"
- "breathing composition"
- "abundant negative space"

---

## 🎞️ עדשה ועומק שדה

**עדשת ברירת מחדל:** 35mm
- לסצנות אינטימיות-ביתיות
- נותן feel של "זיכרון", לא "אקשן"

**עדשת תקריב:** 50mm או 85mm
- לפורטרטים
- ל-bokeh חזק

**עדשת מקרו:** 100mm
- לפרטים — תכשיטים, מסך טלפון, חפצי שולחן

### עומק שדה:
- **רדוד מאוד** (f/1.4-2.0) — לפרטים, פורטרטים
- **רדוד-בינוני** (f/2.8-4.0) — לסצנות שולמות
- **בינוני** (f/5.6) — לסצנות רחבות יותר

### מילות מפתח לפרומפט:
- "35mm lens"
- "shallow depth of field"
- "soft focus background"
- "macro lens close-up" (לפרטים)
- "f/1.8 aperture aesthetic"

---

## 🎬 תנועה (לוידאו)

### תנועות מצלמה מועדפות:

**1. Slow Push-In**
- המצלמה זוחלת לאט קדימה
- אורך: 6-8 שניות
- שימוש: למשוך את הצופה אל תוך הסצנה
- מילות מפתח: "slow push-in", "gradual dolly forward"

**2. Subtle Drift**
- המצלמה זזה אופקית-קל בקצב נשימה
- אורך: 4-6 שניות
- שימוש: לתת תחושת חיים בלי דרמה
- מילות מפתח: "gentle handheld drift", "subtle horizontal movement"

**3. Static with Motion**
- המצלמה לא זזה. המוטיב בתוך הפריים זז.
- אורך: 4-8 שניות
- שימוש: לרגעים מדיטטיביים
- מילות מפתח: "static camera", "subject moves within frame"

**4. Slow Pull-Back**
- המצלמה זזה אחורה לאט
- אורך: 6-8 שניות
- שימוש: חשיפה הדרגתית של הקשר
- מילות מפתח: "slow pull-back", "gradual reveal"

### תנועות להימנע:

- ❌ Fast zoom (זום מהיר)
- ❌ Whip pan (סיבוב מהיר)
- ❌ Shake (רעידה)
- ❌ Speed ramping (האטה/האצה)

### תנועות בתוך הפריים:

לעולם אל תשאיר פריים סטטי לחלוטין. תמיד הוסף לפחות תנועה אחת זעירה:
- אדים מקפה
- וילון מתנדנד
- שיער זז ברוח
- עפעף מתעופף
- אגודל גולל

---

## 👤 Character Sheet — הפרוטגוניסטית הקבועה

> **הפרוטגוניסטית הזאת היא לא שלהבת**. היא דמות שמייצגת את הקהל של אימפרוב.

### תיאור פיזי קבוע (אנגלית):

> An Israeli woman in her mid-thirties, shoulder-length dark brown hair in soft natural waves, clean face with minimal makeup, contemplative brown eyes, fair skin with subtle peach undertones. She wears a soft beige linen or thick cotton t-shirt and wide black trousers. Minimal gold jewelry — a delicate necklace and small hoop earrings. Short, natural nails.

### תיאור פיזי קבוע (עברית):

> אישה ישראלית בשנות ה-30 לחייה, שיער חום-כהה באורך כתפיים בגלים רכים טבעיים, פנים נקיות עם איפור מינימלי, עיניים חומות מתבוננות, עור בהיר עם אפרסקיות עדינה. לבושה בטי-שירט בז' רך מבד פשתן או כותנה עבה, ומכנסיים שחורות רחבות. תכשיטים זהובים מינימליים — שרשרת דקה ועגילי חישוק קטנים. ציפורניים קצרות וטבעיות.

### Variations:

עבור פרקים שונים, אפשר להוסיף וריאציות קטנות (חולצה אחרת, תספורת אחרת) — אבל **השם, הצבעים העיקריים, וסגנון הלבוש העקבי** צריכים להישמר.

### 🛠️ איך להבטיח קונסיסטנטיות ב-Nano Banana:

1. **תמיד התחל ביצירת character-reference.png** — תמונה ראשונה ממוקדת בדמות בלבד
2. **השתמש בתמונה הזאת כ-reference image** בכל קריאה הבאה
3. **חזור על תיאור הדמות בכל פרומפט** — אל תסמוך רק על התמונה
4. **בדוק קונסיסטנטיות** — אם הדמות נראית שונה, צור מחדש

---

## 🏠 Location Sheet — המקום הקבוע

### תיאור (אנגלית):

> A modern home apartment in Tel Aviv, warm minimalist style. Light oak wood desk, a tan-orange designer chair, large houseplants (monstera, fiddle leaf fig), open bookshelves with books in Hebrew and English. Light parquet flooring. Cream-white linen sheer curtain on a large east-facing window. Beige-cream walls.

### תיאור (עברית):

> דירה ביתית-עירונית מודרנית בתל אביב, סגנון מינימליסטי-חם. שולחן עץ אלון בהיר, כיסא שזוף-כתום של מעצב, צמחי בית גדולים (מונסטרה, פיקוס), מדפי ספרים פתוחים עם ספרים בעברית ואנגלית. רצפת פרקט בהירה. וילון פשתן לבן-שמנת חצי-שקוף על חלון גדול הפונה למזרח. קיר בז'-קרם.

### לוקיישנים נוספים אפשריים:

- **בית קפה** — עץ חם, חלונות גדולים, אור טבעי, תל אביב/אירופאי
- **מכונית** — פנים מודרני, אור שמש דרך שמשה, רחוב תל אביבי מטושטש בחוץ
- **חדר שינה** — אור לילה רך, מנורה זהובה, מצעים לבנים
- **מטבח** — כלים פשוטים, צמחים בעציץ, אור בוקר

---

## 📝 טיפוגרפיה — חוק ברזל

> **כלל מוחלט:** המקום היחיד שבו מותרת טיפוגרפיה בפאנל הוא **שם הכלי או המותג שעליו הפרק מדבר**. כל יתר הטקסט (וויסאובר, ציטוטים, CTA, קרדיטים) **נוסף בעריכה ב-CapCut** — לא נוצר ב-Nano Banana.

### מה אסור — בשום פאנל בשום מקרה:

- ❌ **טיפוגרפיה בעברית** — בכלל. שום טקסט עברי בתמונה.
- ❌ **משפטים באנגלית** — לא ציטוטים, לא CTA, לא משפטי-מפתח.
- ❌ **טקסטים מומצאים** על מסכים (LinkedIn posts, סטוריז, וכו') שאינם שם המותג.

### מה כן מותר:

- ✅ **שם הכלי/מותג שמדברים עליו** — בעברית או אנגלית, בעיצוב הלוגו או בטקסט פשוט.

### תהליך זיהוי המותג בכל פרק (חובה לסוכן):

לפני שמתחילים לכתוב פאנלים, הסוכן חייב:

1. **לזהות את הכלי/מותג המרכזי** מהתסריט/תמליל. דוגמאות: Claude Code, ChatGPT, Notion, Cursor, Gemini, Perplexity, Midjourney.
2. **לאתר את צבעי המותג מהידע**:
   - Anthropic / Claude Code: **אורנג' חם** (~#DA7756 / #C96342)
   - OpenAI / ChatGPT: ירוק כהה (#10A37F) או שחור
   - Notion: שחור/לבן מינימלי
   - Cursor: לבן/אפור עם אקסנט אקווה
   - Gemini: גרדיאנט כחול-סגול-ורוד
   - Perplexity: cyan/אקווה
   - Midjourney: שחור/לבן
   - **אם המותג לא ברשימה — להשתמש בידע הכללי או להזהיר את המשתמשת.**
3. **לתכנן את הפאנל הטיפוגרפי כשתי גרסאות**:
   - **גרסה A:** ניסיון להציג את הלוגו הרשמי של המותג
   - **גרסה B:** טקסט פשוט עם שם המותג בצבעי המותג, כגיבוי
4. בסטוריבורד, לפאנל המותג, לציין מפורשות שני האופציות והמשתמשת תבחר.

### כללי עיצוב לפאנל המותג:

- רקע: לבן-שמנת (`#F5EFE6`) או הצבע שמנוגד הכי טוב לצבע המותג.
- מיקום: שם המותג ממוקם במרכז או בשליש הזהוב, מקום נוצר סביבו.
- גודל: שם המותג ממלא 30-50% מרוחב הפריים (לא קטן, לא ענק).
- אסור לערב צבעים אחרים פרט לצבע המותג + רקע.
- אסור לוגואים אחרים, אייקונים אחרים, או טקסט נוסף.

### מה עושים עם הטקסטים האחרים?

הוויסאובר, ציטוטים, ה-CTA — **לא** הופכים לפאנלים טיפוגרפיים. במקום זה:
- **וויסאובר:** המשתמשת מוסיפה ב-CapCut על הסצנות הוויזואליות.
- **CTA:** הסטוריבורד יכלול **פאנל סצנה ויזואלית** שתשמש כרקע ל-CTA, והמשתמשת תניח את הטקסט עליה ב-CapCut. הפאנל הזה צריך להיות "פתוח" — מרחב שלילי נדיב ב-1/3 התחתון או הצד השני של הפריים, איפה שהטקסט יכול להישב נוח.
- **משפטי מפתח:** שאלות ל-engagement → סצנה ויזואלית שמרמזת על שאלה (close-up עיניים, יד עוצרת, וכו'), והטקסט נוסף בעריכה.

---

## 📝 טיפוגרפיה — דברים שכבר לא בשימוש

> **הסקציה הזאת נשארת לתיעוד היסטורי. החוק החדש לעיל גובר.**

הסגנון המקורי כלל פונטים serif אלגנטיים בעברית ובאנגלית, צבעי בורדו ואפור-כהה לטקסטים דרמטיים. כל זה **לא מיוצר ב-Nano Banana** עוד. אם רוצים אפקט טיפוגרפי דרמטי כזה — מוסיפים אותו ב-CapCut על סצנה ויזואלית.

---

## 🔧 פרומפט-טמפלייט סטנדרטי

לכל פרומפט תמונה (Nano Banana), השתמש במבנה הזה:

```
[Style anchor] + [Character description] + [Location description] +
[Specific scene action] + [Camera angle and lens] + [Lighting] +
[Color palette repeat] + [Texture details] + [Mood/atmosphere] +
[Small specific detail]
```

### דוגמה מלאה:

> Cinematic 35mm photography in the style of Sofia Coppola, [character description], standing in [location description], looking at [specific action], shot at eye level with shallow depth of field, soft golden morning light filtering through cream linen curtains, color palette of dusty peach and cream beige with subtle gold accents, soft linen texture of her shirt, gentle film grain, atmosphere of quiet contemplative pause, small detail of [specific small detail].

---

## 🎯 רשימת בדיקה לכל פאנל

לפני שאתה שולח פרומפט ל-Nano Banana או Veo, וודא שהפרומפט כולל:

- [ ] Style anchor — Sofia Coppola style explicitly mentioned
- [ ] Character — תיאור פיזי מלא של הדמות (גם אם יש reference image)
- [ ] Location — תיאור המקום
- [ ] Camera angle — eye level / top-down / POV / וכו'
- [ ] Lens — 35mm / 50mm / macro
- [ ] Depth of field — shallow / medium
- [ ] Lighting — מקור, צבע, רכות
- [ ] Color palette — אפרסק, קרם, זהב
- [ ] Texture — פשתן, עץ, זכוכית
- [ ] Mood — quiet / intimate / contemplative
- [ ] Specific detail — פרט קטן שנותן אמינות

אם חסר משהו מ-11 הסעיפים — חזק את הפרומפט.

---

## 🚫 מה לא לעשות

1. **אל תייצר תמונות "AI-looking"** — חלקלקות יותר מדי, צבעים רוויים מדי, פנים מסומטרות מדי
2. **אל תכלול מותגים** — לא Apple, לא Instagram (UI כללי בסדר), לא לוגואים
3. **אל תייצר "stock photo vibe"** — נשים מחייכות בסטודיו, רקע לבן-קלינית
4. **אל תטשטש את הפנים יותר מדי** — שלהבת רוצה דמויות אמיתיות עם אישיות
5. **אל תוסיף אפקטים מיוחדים** — אש, ניצוצות, particles — לא מתאים לסגנון

---

## ✨ הבדיקה הסופית

אחרי שיצרת תמונה, שאל את עצמך:

> "האם זה יכול היה להופיע בסרט של Sofia Coppola?"

- אם כן → התמונה מתאימה
- אם לא → תאם את הפרומפט וצור מחדש

זכור: **רכות, לא חדות. אינטימיות, לא דרמטיות. ניאו-ריאליסטית, לא ייפויי.**
