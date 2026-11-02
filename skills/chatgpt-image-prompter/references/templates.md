# templates - נוסחאות ותבניות

תבניות מוכנות. הכל באנגלית (שפת הפלט המומלצת). ערך בסוגריים מרובעים = placeholder.

תוכן:
1. בלוקים מתויגים (המבנה הנייטיבי)
2. תבניות יצירה לפי סוג תוצר
3. תבניות עריכה
4. מרובה-תמונות לפי אינדקס
5. עוגן דמות (עקביות לאורך סדרה)

---

## 1. בלוקים מתויגים - המבנה הנייטיבי של gpt-image-2

לבקשה מורכבת, בלוקים בשורות נפרדות מנצחים פסקה אחת. פותחים בהצהרת שימוש מיועד.

**תבנית:**
```
[Intended use — e.g. "Create a 4:5 vertical marketing poster"].

Scene: [background / environment / time / weather].
Subject: [who/what, concrete detail — materials, count, wardrobe].
Style: [medium, realism level, art direction].
Composition: [framing, angle, placement callouts].
Lighting & mood: [light quality, emotional tone].
Constraints: [no watermark, no logos, preserve X...].
Text (verbatim): "[exact words]" — [font style, size, color, placement].
```

לבקשה פשוטה: בריף משפטי קצר בסדר סצנה ← נושא ← פרטים ← אילוצים, עם ציון השימוש.

---

## 2. תבניות יצירה לפי סוג תוצר

**אינפוגרפיקה** (מומלץ Thinking / quality=high):
```
Create a detailed infographic explaining [topic] for [audience].
Show the flow/structure: [element 1] → [element 2] → [element 3]...
Clean layout, clear hierarchy, legible labels. [Aspect ratio].
```

**פוטוריאליזם ("רגע אמיתי"):**
```
Create a photorealistic candid photograph of [subject with real texture — pores,
wrinkles, fabric wear]. [Action]. Shot like a 35mm film photograph, [framing] at
eye level, [lens, e.g. 50mm]. [Natural light], shallow depth of field, subtle film
grain, natural color balance. Honest and unposed. No glamorization, no heavy retouching.
```

**לוגו** (אפשר n=4 וריאציות):
```
Create an original, non-infringing logo for [company], a [business type].
[Personality: warm/bold/timeless]. Clean vector-like shapes, strong silhouette,
balanced negative space, scalable at small and large sizes. Flat design, minimal
strokes. Plain background. Single centered logo with padding. No watermark.
```

**מוקאפ UI** ("כאילו כבר שוגר"):
```
Create a realistic [mobile/web] UI mockup for [product]. Show [screens/sections
with real interface elements — header, list, cards]. Practical and easy to use.
[Background color], clear typography, minimal decoration. Looks like a real,
shipped app. [Place in an iPhone frame, if relevant].
```

**קומיקס** (beat לכל פאנל):
```
Create a [layout, e.g. vertical 4-panel] comic.
Panel 1: [concrete visual beat].
Panel 2: [beat].
Panel 3: [beat].
Panel 4: [beat].
[Style]. [Aspect ratio].
```

**כרטיס/מוצר עם טקסט:**
```
Create a [card/product] illustration. Scene: [...]. Mood: [...]. Style: [premium
photography, soft lighting, realistic textures]. Constraints: original artwork, no
trademarks, no watermarks, no logos. Include ONLY this text (verbatim): "[copy]".
```

---

## 3. תבניות עריכה

הכלל: **"change only X" + "keep everything else the same"**, עם רשימת שימור, וחזרה עליה בכל איטרציה.

**הסרה / שינוי מקומי:**
```
[Remove the X / Change the Y to Z] in this image. Do not change anything else.
```

**החלפה מדויקת (interior/object swap):**
```
In this image, replace ONLY [X] with [Y]. Preserve camera angle, lighting, shadows,
and surrounding objects. Keep all other aspects unchanged. Photorealistic contact
shadows and texture.
```

**Style transfer:**
```
Use the same visual style from the input image (palette, texture, brushwork) and
generate [new subject/scene]. Keep [background/framing]. Do not add extra elements.
```

**Try-on (שימור זהות קריטי):**
```
Dress the person using the provided clothing image(s). Do NOT change the face,
features, skin tone, body shape, pose, hair, or identity. Replace ONLY the clothing,
fitting naturally with realistic fabric behavior. Match lighting, shadows, and color
temperature to the original. Do not change background, camera angle, or framing. No
added accessories, text, logos, or watermarks.
```

**Sketch → render:**
```
Turn this drawing into a photorealistic image. Preserve the exact layout,
proportions, and perspective. Choose realistic materials and lighting consistent
with the sketch intent. Do not add new elements or text.
```

**חילוץ מוצר (רקע שקוף):**
```
Extract the product from the input image. Output: transparent background (RGBA PNG),
crisp silhouette, no halos/fringing. Preserve product geometry and label legibility
exactly. Optional: subtle realistic contact shadow in the alpha. Do not restyle;
only remove background and lightly polish.
```

**relight / weather:**
```
Make it [a winter evening with snowfall / golden hour / overcast dusk]. Change only
environmental conditions — lighting, shadows, atmosphere. Preserve identity,
geometry, camera angle, and object placement.
```

---

## 4. מרובה-תמונות לפי אינדקס

מפנים לכל קלט לפי מספר ותיאור, ומתארים איך הם מתקשרים.

**תבנית:**
```
Image 1: [description, e.g. the scene]. Image 2: [description, e.g. the dog].
Place [the dog from Image 2] into [the setting of Image 1, next to the woman].
Match lighting, composition, perspective, scale, and shadows. Do not change anything else.
```

---

## 5. עוגן דמות - עקביות לאורך סדרה

שלב 1 - יצירת עוגן (נועל מראה):
```
Create a [style] illustration introducing a main character.
Character: [detailed appearance, proportions, outfit, tone].
Constraints: original character, no text, no watermarks, plain background to
showcase the character.
```

שלב 2 - המשך (אותה דמות, סצנה חדשה):
```
Continue using the same character. Scene: [new scene + action].
Character consistency: same [outfit], same facial features, proportions, and color
palette. Do not redesign the character. No text, no watermarks.
```
מריצים את שלב 2 כעריכה שמפנה לתמונת העוגן, לאורך כל פריט בסדרה.
