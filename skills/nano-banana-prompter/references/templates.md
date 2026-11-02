# templates - נוסחאות ותבניות

תבניות מוכנות להרכבת הפרומפט. כל התבניות באנגלית (שפת הפלט המומלצת). הערך בסוגריים מרובעים הוא placeholder.

תוכן:
1. יצירה נרטיבית (תמונה בודדת)
2. מבנה Pseudo-Code (סצנה מורכבת / סדרה)
3. חמש תבניות עריכה
4. טקסט בתמונה
5. תמונות רפרנס (הקצאת תפקידים)
6. מידע אמיתי מהרשת

---

## 1. יצירה נרטיבית - תמונה בודדת

הנוסחה: `[Subject] + [Action] + [Location/context] + [Composition] + [Style]`. פרטים חשובים ראשונים.

**תבנית:**
```
[Subject: who/what, with concrete detail — count, age, clothing, materials].
[Action: what they're doing, pose, relationships].
[Location/context: place, time, weather, environment].
[Composition: shot type, angle, lens, depth of field, framing].
[Style: medium, realism level, lighting, color grading, mood]. [Aspect ratio]. [Resolution].
```

**דוגמה (מתוך המדריך הרשמי, כמופת מבנה):**
```
A striking fashion model wearing a tailored brown dress, sleek boots, holding a
structured handbag. Posing with a confident, statuesque stance, slightly turned.
A seamless deep cherry-red studio backdrop. Medium-full shot, center-framed.
Fashion magazine editorial style, shot on medium-format analog film, pronounced
grain, high saturation, cinematic lighting. 4:5 aspect ratio, 2K.
```

---

## 2. מבנה Pseudo-Code - סצנה מורכבת או סדרה

מתי: סצנות עתירות פרטים, קמפיין, עקביות דמות לאורך כמה תמונות, או כשהמשתמש יאטרֵר על משתנה אחד. היתרון: משנים משתנה אחד, השאר נשאר קבוע ⟵ יציבות.

**תבנית:**
```
[VARIABLES]
SUBJECT = "[concrete subject description]"
LOCATION = "[environment description]"
LIGHTING = "[lighting setup]"
CAM = "[camera, lens, aperture, focus]"
STYLE = "[medium, grading, mood]"

[EXECUTION]
Render SUBJECT in LOCATION. Apply LIGHTING. Use CAM for [look].
[Aspect ratio]. [Resolution].
```

לאיטרציה: משנים רק את המשתנה הרלוונטי ומשאירים את השאר. אפשר להוסיף `[REASONING: calculate true light paths based on light source position]` אם הפיזיקה יוצאת שגויה.

---

## 3. חמש תבניות עריכה

הכלל המשותף: **תמיד לומר מה נשאר**, אחרת המודל משנה דברים שלא ביקשו.

**הסרה (Remove):**
```
Using this image, remove [specific element]. Keep everything else in the image
exactly the same, preserving the original style, lighting, and composition.
```

**הוספה (Add):**
```
Using this image, add [new object with concrete detail] at [precise location in
the scene]. Match the existing lighting and perspective. Keep everything else the same.
```

**החלפה (Replace):**
```
Replace the [X] with [Y that matches the scene]. Match the lighting and shadows
of the original. Keep everything else exactly the same.
```

**שינוי תאורה (Relight):**
```
Relight this scene for [condition, e.g. golden hour]. [Shadow direction, e.g. long
shadows from the viewer's left]. Warm the highlights to [temp], cool the shadows to
[temp]. Keep composition and subject unchanged.
```

**Style transfer:**
```
Recreate this image in [target style, e.g. Van Gogh oil painting]. Keep the layout
of the subject and scene unchanged. [Style specifics: brushwork, texture, palette].
Do not add new elements.
```

---

## 4. טקסט בתמונה

- **המילים המדויקות במרכאות:** `the words "URBAN EXPLORER"`. מקבלים אותן verbatim מהמשתמש.
- **מתארים פונט:** `bold white sans-serif` או שם פונט (`Century Gothic`).
- **שכבות ומיקום:** אפשר לבקש `text behind the subject's head but legible` - המודל בונה מסכת occlusion לבד.
- **טריק text-first:** אם הטקסט מורכב, קודם לגבש איתו את הטקסט בשיחה, ואז לבקש תמונה עם הטקסט הזה.
- **לוקליזציה:** כותבים במרכאות את המחרוזת בשפת היעד, או מבקשים לתרגם טקסט קיים בתמונה לשפה אחרת.

**דוגמה:**
```
A magazine cover. Title text at the top: "CREATIVE FUTURE" in a bold sans-serif
font, white. Ensure the text sits behind the subject's head but remains legible.
```

---

## 5. תמונות רפרנס - הקצאת תפקידים

עד 14 תמונות. הכלל: **תפקיד מפורש לכל רפרנס.**

**תבנית:**
```
Use Image A for [role, e.g. the character's facial features and identity].
Use Image B for [role, e.g. the pose and body position].
Use Image C for [role, e.g. the background environment].
[New scenario / instruction combining them].
Maintain [what must stay constant, e.g. facial structure from Image A] exactly.
```

תפקידים אפשריים: זהות/דמות, פוזה/קומפוזיציה, סגנון/אסתטיקה, תאורה/אווירה, סביבה/רקע, לוגו/מותג.

---

## 6. מידע אמיתי מהרשת

כשרוצים שהתמונה תתבסס על נתון אמיתי (מזג אוויר, אירוע).

הנוסחה: `[Search/data request] + [Analytical task] + [Visual translation]`.

**דוגמה:**
```
[Search for the current weather in San Francisco]. [Use this data to set the mood
— if raining, grey and wet]. [Visualize as a miniature city-in-a-cup inside a
modern smartphone UI].
```
