# vocabulary - בנק השפה המקצועית

המונחים שמכוונים את המודל. שולפים מכאן במקום לכתוב מעורפל. הכל באנגלית (נכנס לפרומפט).

עיקרון ל-gpt-image-2: **שפת מצלמה ומנופי איכות ממוקדים מכוונים ריאליזם טוב יותר מ"8K/ultra-detailed" גנרי.**

---

## מנופי איכות (quality levers) - ממוקדים בלבד

- `subtle film grain` - מרקם פילם, אותנטי.
- `textured brushstrokes` - לציור/איור.
- `macro detail` - פרטי מיקרו.
- `shallow depth of field` - בוקה, הפרדת נושא.
- `natural color balance` - צבע לא-מלוטש.

הימנע מ: `8K`, `ultra-detailed`, `masterpiece` - גנרי, פחות אפקטיבי.

---

## מצלמה ועדשות (לפוטוריאליזם)

- `35mm film photograph` / `iPhone snapshot quality` - אותנטי, לא מלוטש.
- `50mm lens` - פרספקטיבה טבעית.
- `85mm lens` - פורטרט, בוקה.
- `macro lens` - פרטים.
- framing: `medium close-up`, `wide shot`, `top-down`, `eye-level`, `low-angle`.

## שפת "רגע אמיתי" (למניעת מראה AI מלוטש)

- `candid`, `unposed`, `honest`, `everyday detail`
- `real skin texture — pores, wrinkles, sun texture`
- `worn materials`, `fabric wear`, `imperfections`
- `No glamorization, no heavy retouching, no cinematic grading`

---

## תאורה ומצב רוח

- `soft diffuse light` / `soft coastal daylight` - רך, טבעי.
- `golden hour` - חם, צללים ארוכים.
- `high-contrast` - דרמטי.
- `overcast` / `dusk` / `winter evening with snowfall` - מזג אוויר/זמן.

---

## מדיום וסגנון

- `photorealistic` - צילום.
- `hand-painted watercolor look, soft outlines` - אקוורל (לספרי ילדים).
- `flat design, vector-like shapes` - לוגו/אייקון/אינפוגרפיקה.
- `premium product photography, studio lighting, sharp label printing` - מוצר/מרצ'.
- `hand-drawn retro anime style` / `plushie style` - סגנונות איור.
- `3D render` - תלת-ממד.

---

## אילוצים נפוצים (constraints)

שליליים: `no watermark`, `no logos`, `no trademarks`, `no extra text`, `no added accessories`, `no halos/fringing`.

invariants (שימור): `preserve identity`, `preserve geometry`, `preserve layout`, `preserve label legibility`, `preserve brand elements`, `keep everything else the same`, `do not redesign the character`.

---

## טקסט בתמונה

- המילים המדויקות ב`"quotes"` או ב-ALL CAPS.
- `verbatim, no extra characters`, `appears once`, `perfectly legible`.
- טיפוגרפיה: `bold sans-serif, high contrast, centered, clean kerning`.
- למילה קשה: לאיית אות-אות בפרומפט לשיפור דיוק.
- לוקליזציה: לתרגם טקסט בתמונה קיימת בלי לשנות פריסה ("translate the text to Spanish, do not change any other aspect").
