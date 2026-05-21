# 🛠️ Prompt Formulas — Nano Banana ו-Veo 3.1

> **הסוכן AI יקרא את הקובץ הזה לפני שלבים 5-6 (יצירת תמונות ווידאו).**

---

## 🎨 חלק 1: Nano Banana / Gemini 2.5 Flash Image

### ה-API:

```python
from google import genai
from google.genai import types
import os

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[
        prompt_text,        # הפרומפט
        reference_image,    # אופציונלי — עד 3 תמונות
    ]
)
```

### 🎯 5 העקרונות (Camera-First Prompting)

> **חשוב:** הנוסחה הזו עודכנה לאחר ניתוח פערים בין פרומפטים שלא עבדו לבין פרומפטים שעבדו.
> המודל לא מבין שפה קולנועית — הוא מבין אילוצים גיאומטריים מפורשים.

**עקרון 1 — אילוצים גיאומטריים, לא שפה קולנועית.**
"Over-the-shoulder" / "POV" / "Dutch angle" — אלה הוראות למפיק, לא למודל. צריך לתרגם:
- ❌ "POV over-the-shoulder angle"
- ✅ "Camera positioned behind the woman, slightly above shoulder level, looking forward toward the laptop. Back of head visible, shoulder in foreground."

**עקרון 2 — כל אלמנט שמוזכר חייב להיות בקאדר.**
אם הזכרת עיניים חומות מהורהרות בשוט מאחור — זה סותר את עצמו. המודל ינסה לרצות את שניהם ויעוות.
- ❌ בשוט OTS: "An Israeli woman in her mid-thirties with contemplative brown eyes..."
- ✅ בשוט OTS: "Back view of a woman with shoulder-length wavy dark brown hair. Face not visible."

**עקרון 3 — Negative Geometry מפורש.**
מה שלא רואים זה לא תוספת בסוף — זה חלק מהקומפוזיציה.
- ✅ "no full face visible"
- ✅ "at most a small partial profile"
- ✅ "back view only"
- ✅ "shoulder occupies foreground"

**עקרון 4 — טקסט ומסכים מושכים את המודל לפרונטלי.**
אם יש טקסט שצריך להיות קריא, המודל יבחר זווית ישרה. אם רוצים שהמסך גם קריא וגם בזווית — אילוץ מפורש:
- ✅ "Screen in sharp focus, slightly angled — readable but not fully frontal."

**עקרון 5 — סדר הפרומפט קובע משקל.**
המודל קורא מלמעלה למטה ושוקלל את הראשונות חזק יותר. לכן הקומפוזיציה הולכת ראשונה, לא בסוף.

---

### פורמולת פרומפט מנצחת (גרסה 2.0):

```
1. Style anchor (Sofia Coppola, 35mm cinematic)
2. Camera position — exactly where, what height, what angle
3. What IS visible — specific parts only (back, profile, half body)
4. What is NOT visible — explicit prohibitions
5. Subject in focus + depth of field
6. Foreground / Background composition
7. Lighting (source, direction, softness)
8. Color palette
9. Setting / Location
10. Texture details
11. Mood / atmosphere
12. Specific small detail (anchors authenticity)
13. Aspect ratio (9:16)
14. Negative prompts (artifacts, distortions to avoid)
```

### דוגמת פרומפט מלא — "אישה צופה ב-LinkedIn post" (Camera-First):

```
Cinematic 35mm photography in the style of Sofia Coppola.

Strict over-the-shoulder shot:
The camera is positioned behind the woman, slightly above shoulder level,
looking forward toward the phone screen.

The woman is seen only from behind:
- back of head with shoulder-length wavy dark brown hair visible
- shoulder and part of upper back in the foreground
- no full face visible (at most a small partial profile at the edge)
- soft beige linen t-shirt sleeve in the foreground

The phone screen is the main focus:
- sharp and readable
- showing a LinkedIn post by a man in a gray suit
- title "How Claude Code transformed my workflow"
- 247 likes counter visible
- small commenter avatars below

Depth of field:
- shallow depth of field
- foreground shoulder slightly blurred
- background kitchen blurred
- screen in sharp focus

Setting: warm minimalist Tel Aviv apartment kitchen, kettle and plate of
pancakes on counter at the edge of frame.

Lighting: soft ceiling light mingling with window light from behind,
creating gentle rim light on the back of her hair.

Color palette: dusty peach, cream beige, soft white. Gentle film grain.

9:16 vertical format.

Avoid: full frontal face view, oversaturated colors, harsh lighting,
generic AI aesthetics, distorted hands, extra fingers, text artifacts.
```

### חוקי ברזל ל-Nano Banana:

1. **תמיד הוסף "9:16 vertical format"** — זה לא ברירת מחדל
2. **תיאור הדמות רק על מה שבקאדר** — לא להזכיר עיניים אם לא רואים פנים
3. **השתמש ב-reference images רק כשהדמות/מקום בקאדר** — אחרת זה מעוות (ראה סעיף "Smart References" למטה)
4. **אל תוסיף יותר מ-3 reference images** — Nano Banana מתבלבל
5. **תיאור פרט קטן ספציפי** — נותן אמינות (אדים, השתקפות, וכו')
6. **קומפוזיציה ראשונה, פרטים אחרונים** — סדר הפרומפט = משקל

### Smart References — מתי להעביר character_reference?

> **בעיה היסטורית:** העברת character reference לפאנל שלא צריך אותה גורמת לעיוותים.
> המודל מנסה "להראות את הדמות" גם כשהפאנל לא דורש אותה.

**העבר character_reference רק אם:**
- ✅ הפאנל מציין במפורש שהדמות בקאדר ומזוהה (פנים/חצי גוף/גוף שלם)
- ✅ זה שוט OTS שבו רואים את הגב/כתף של הדמות

**אל תעביר character_reference אם:**
- ❌ זה close-up של חפץ (טלפון, ספר, כוס)
- ❌ זה wide shot של מקום ריק
- ❌ זה פאנל טיפוגרפי (טקסט על מסך)
- ❌ זה shot של ידיים בלבד או חלק גוף ספציפי שלא מזהה את הדמות

**העבר location_reference רק אם:**
- ✅ הפאנל מתרחש במקום הקבוע (דירה / בית קפה הקבוע)
- ❌ אל תעביר ב-close-ups שלא רואים את המקום

### יצירת Character Reference Sheet (פעם אחת לפרק):

```python
# שלב 1 - יצירת character reference
prompt = """
Character reference sheet, neutral pose, full body and headshot:
An Israeli woman in her mid-thirties with shoulder-length wavy dark
brown hair, contemplative brown eyes, fair skin with peach undertones,
wearing soft beige linen t-shirt and wide black trousers, minimal gold
jewelry. Three views: front, three-quarter, side profile. Plain
neutral background. Cinematic 35mm photography style. 1:1 aspect ratio.
"""

response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[prompt]
)

# שמור כ-character-reference.png
```

### יצירת Location Reference Sheet:

```python
prompt = """
Location reference: Modern home apartment in Tel Aviv, warm minimalist
style. Light oak wood desk, tan-orange designer chair, large monstera
plant, open bookshelves, light parquet flooring, cream-white linen sheer
curtain on east-facing window, beige-cream walls. Wide establishing shot,
no people, golden morning light. Cinematic 35mm photography style.
16:9 aspect ratio.
"""
```

### תיקון תמונות בעייתיות:

| בעיה | פתרון בפרומפט |
|------|----------------|
| הדמות נראית שונה | חזק את התיאור הפיזי + reference image |
| צבעים רוויים מדי | "muted colors", "low saturation", "dusty palette" |
| התמונה "AI-לוקינג" | "natural", "imperfect", "documentary feel" |
| פנים מסומטרות | "asymmetrical face", "slight imperfection" |
| תאורה דרמטית מדי | "soft diffused light", "overcast", "no harsh shadows" |
| רקע סטריאוטיפי | תאר רקע ספציפי בפרטים |
| חיתוך גוף לא נכון | ציין "shot from waist up" / "full body" / "headshot" |

### Negative Prompts (מה לא לכלול):

הוסף בסוף הפרומפט:

```
Avoid: oversaturated colors, harsh lighting, smiling stock photo
expressions, generic AI aesthetics, perfect symmetry, plastic-looking
skin, fashion magazine pose, motion blur, lens flare, vignette overlay,
text artifacts, distorted hands, extra fingers.
```

---

## 🎥 חלק 2: Veo 3.1

### ה-API:

```python
from google import genai
from google.genai import types
import time
import os

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Image-to-video עם first frame
operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=video_prompt,
    image=first_frame_image,  # types.Image
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        duration_seconds=8,
        resolution="1080p",
    )
)

# המתנה ארוכה (1-3 דקות)
while not operation.done:
    time.sleep(15)
    operation = client.operations.get(operation)

# הורדה
video_uri = operation.result.generated_videos[0].video.uri
```

### פורמולת פרומפט וידאו מנצחת:

```
[Camera movement description over X seconds]
+ [Subject action — one specific motion]
+ [Environmental motion — wind, steam, light shift]
+ [Continuous element — what stays the same]

Audio: [Soundscape description]. [Specific sound at specific time].
[What NOT to include — "No music. No voiceover."]

Style: [Cinematic anchor]. [Aspect ratio]. [Resolution]. [Duration].
```

### דוגמת פרומפט מלא (push-in על טלפון):

```
The camera slowly pushes in toward the phone screen over 8 seconds,
starting from a top-down 45-degree angle of the wooden desk and gradually
tilting to a near-straight overhead view of the phone screen. As the
camera moves closer, the steam from the coffee mug drifts gently to the
right, and the woman's thumb moves slowly downward in a single, deliberate
scrolling gesture across the screen. The sheer linen curtain in the
background sways almost imperceptibly with a soft morning breeze. Shallow
depth of field maintained throughout — the phone screen stays in sharp
focus while the surrounding desk softly blurs.

Audio: Quiet morning ambience. The faint sound of distant traffic from
an open window. A single soft notification chime rings once at the
3-second mark. The subtle whoosh of the thumb sliding across the glass
screen. No music. No voiceover.

Style: Cinematic 35mm, in the style of Sofia Coppola's morning scenes
from "Lost in Translation". Soft golden hour light, dusty peach and
cream beige palette, gentle film grain.

Duration: 8 seconds. Aspect ratio: 9:16. Resolution: 1080p.
```

### חוקי ברזל ל-Veo 3.1:

1. **אורך מקסימלי: 8 שניות** — תכנן בהתאם
2. **9:16 לרילסים** — תמיד
3. **תאר תנועה, לא תמונה סטטית** — הפריים מספר את התמונה
4. **אודיו תמיד נפרד** עם המילה "Audio:"
5. **כתוב מפורש "No music. No voiceover."** — אחרת Veo מוסיף אוטומטית
6. **תנועה אחת מרכזית** — לא רשימה של תנועות

### החלטה: First Frame בלבד או First+Last Frame?

| מצב | המלצה | למה |
|-----|--------|-----|
| Push-in / pull-back | **First בלבד** | התנועה כל כך עדינה שאין צורך באנגד |
| תנועת דמות (הליכה, מבטים) | **First בלבד** | Veo טוב באנמציה אורגנית |
| חיבור בין שתי סצנות | **First + Last** | זה הוא מקרה השימוש המקורי |
| טרנספורמציה (ריק → מלא) | **First + Last** | חשוב לקבע נקודת סיום |
| ספק | **First בלבד** | יותר טבעי, פחות artifacts |

### תנועות מצלמה — סינטקס מומלץ:

**Push-in איטי:**
> "The camera slowly pushes forward over 8 seconds"

**Pull-back איטי:**
> "The camera slowly pulls back over 8 seconds, gradually revealing more of the room"

**Drift אופקי:**
> "The camera drifts gently from left to right, mimicking a soft handheld breath"

**Pan איטי:**
> "The camera pans slowly from the window to the desk over 6 seconds"

**Tilt:**
> "The camera tilts upward slowly, starting from her hands on the keyboard and ending at her face"

**סטטי עם תנועת תוכן:**
> "Static camera. The subject's hand reaches forward to pick up the cup. Steam rises continuously."

### תנועות להימנע:

- ❌ "fast zoom in"
- ❌ "whip pan"
- ❌ "shake"
- ❌ "spinning camera"
- ❌ "rotating 360 degrees"

### אודיו — סינטקס מומלץ:

**אווירה רקעית:**
> "Audio: Quiet ambient sounds of a Tel Aviv morning."

**אירוע סאונד ספציפי:**
> "Audio: A soft notification chime at the 3-second mark."

**אפקטים סובבים:**
> "Audio: The subtle whoosh of fabric as she moves."

**שלילה:**
> "Audio: No music. No voiceover. Only ambient sound."

### תיקון תנועות בעייתיות:

| בעיה | פתרון |
|------|--------|
| הוידאו רועד / לא יציב | "stable, smooth motion", "tripod-mounted feel" |
| תנועה מהירה מדי | "slowly", "gradually", "over X seconds" |
| Veo ממציא תנועה לא רצויה | תאר מפורש מה לא צריך לקרות: "the background remains still" |
| הדמות "מתאדה" | "the woman remains in frame throughout" |
| אדים/וילון לא טבעיים | "subtle", "barely perceptible", "natural physics" |
| מוזיקה רקע לא רצויה | "No background music. Only [specific sound]" |

### עלות צפויה:

- **Veo 3.1:** ~20 קרדיטים לוידאו ב-Flow / ~$0.50-2.00 ב-Gemini API
- **Nano Banana:** חינמי במנוי / ~$0.04 לתמונה ב-API

**אסטרטגיה כלכלית לטיזר:**
- 11 פאנלים סך הכל
- מתוכם: 6-7 תמונות סטילס בלבד (חינמיות יחסית)
- 3-4 קליפי וידאו (היקרים)
- עלות מוערכת לטיזר: ~$2-8

### לפני יצירת וידאו — תמיד אשר עם המשתמש:

**הסוכן AI חייב לעצור ולבקש אישור** עם:

```
🎥 מוכן ליצור [N] קליפי וידאו ב-Veo 3.1.
עלות מוערכת: $X-Y / ~Z קרדיטים.
זמן יצירה משוער: X-Y דקות.

הפרומפטים שיישלחו:
1. [קליפ 1: תיאור קצר]
2. [קליפ 2: תיאור קצר]
...

האם להמשיך? (כן / לא / שינויים)
```

---

## 🧪 חלק 3: דוגמאות מלאות לעבודה

### דוגמה 1: Image-to-video של פאנל סטטי + תנועה בתוכו

```python
# שלב 1: צור תמונה ב-Nano Banana
image_prompt = """
[Full Sofia Coppola style prompt for Panel 5 — woman by window]
"""

image_response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[image_prompt]
)
image_bytes = image_response.generated_image.bytes

# שלב 2: שמור והשתמש כ-first frame
with open("temp_frame.png", "wb") as f:
    f.write(image_bytes)

first_frame = types.Image.from_file("temp_frame.png")

# שלב 3: צור וידאו
video_prompt = """
The camera slowly pushes in over 8 seconds. The woman's gaze
shifts gradually from the unfocused middle distance to the floor.
Her chest rises and falls in slow breath. Steam from the forgotten
coffee mug drifts faintly behind her.

Audio: Quiet apartment ambience. A faint distant car horn from outside.
Soft cotton fabric rustling as she breathes. No music. No voiceover.

Style: Cinematic 35mm, Sofia Coppola aesthetic. Soft golden morning
light, dusty peach palette.

Duration: 8 seconds. Aspect ratio: 9:16. Resolution: 1080p.
"""

operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=video_prompt,
    image=first_frame,
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        duration_seconds=8,
        resolution="1080p",
    )
)

while not operation.done:
    time.sleep(15)
    operation = client.operations.get(operation)

# שמור את הוידאו
video_url = operation.result.generated_videos[0].video.uri
```

### דוגמה 2: First + Last frame (טרנספורמציה)

```python
# שני פריימים שונים שמייצגים מצב התחלה ומצב סוף
first = types.Image.from_file("panel_5_anxious.png")  # האישה מודאגת
last = types.Image.from_file("panel_10_calm.png")     # האישה רגועה

video_prompt = """
Smooth cinematic transition over 8 seconds. The woman's facial
expression gradually shifts from anxious tension to calm release.
Her shoulders lower. Her gaze moves from the phone to the window.
The morning light intensifies subtly.

Audio: Quiet morning ambience throughout. A single soft breath
exhale at the 5-second mark. No music.

Style: Cinematic 35mm, Sofia Coppola aesthetic.

Duration: 8 seconds. Aspect ratio: 9:16.
"""

operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=video_prompt,
    image=first,
    config=types.GenerateVideosConfig(
        last_frame=last,
        aspect_ratio="9:16",
        duration_seconds=8,
    )
)
```

---

## 🚨 בעיות נפוצות והפתרון

### 1. "התמונה לא דומה ל-character reference"

**אבחנה:** Nano Banana לא תמיד מכבדת בצורה מדויקת את התמונת הרפרנס.

**פתרון:**
```python
# הוסף את התיאור הפיזי במלואו לפרומפט
# גם אם יש reference image
prompt = f"""
{full_character_description}

{scene_description}

Reference: maintain identical facial features, hair, and clothing
as in the reference image.
"""
```

### 2. "הוידאו יוצא 'AI-לוקינג' — תנועות לא טבעיות"

**אבחנה:** הפרומפט מדבר במונחים סינתטיים, לא קולנועיים.

**פתרון:** השתמש בשפה קולנועית:
- ❌ "make her move smoothly"
- ✅ "the woman shifts her weight naturally, as if caught in an unconscious moment"

### 3. "Veo מוסיף מוזיקה רקע מגה-דרמטית"

**פתרון:** הוסף בסוף ה-Audio block:
```
Audio: [...]
NO music. NO orchestral score. NO ambient pads. Only diegetic sounds —
sounds that exist naturally in the scene.
```

### 4. "התמונות יוצאות עם טקסט מעוות"

**פתרון:** הימנע מתיאור טקסט בפרומפט אלא אם הכרחי. אם הכרחי:
```
The phone screen shows a stylized graphic with the text "Claude Code"
in clean sans-serif. (If the text appears garbled, suggest replacing
in post-production.)
```

עדיף לייצר את הטקסט בעריכה (Photoshop/Premiere), לא ב-Nano Banana.

### 5. "הדמות מתעוותת בין פאנל לפאנל"

**פתרון:** השתמש תמיד באותו seed (אם הכלי תומך) + reference image עקבית + תיאור פיזי זהה.

```python
# Nano Banana לא תומך כרגע ב-seed ידני
# אז בנה reference image חזק והשתמש בה תמיד
```

---

## 📊 רשימת בדיקה לפני יצירה

### לפני Nano Banana:

- [ ] פרומפט כולל את כל 11 הסעיפים מ-`visual-style-guide.md`
- [ ] character reference מצורף (אם רלוונטי)
- [ ] location reference מצורף (אם רלוונטי)
- [ ] aspect ratio צוין (9:16)
- [ ] negative prompts הוספו

### לפני Veo 3.1:

- [ ] תמונה first frame קיימת ו-validated
- [ ] פרומפט מתאר תנועה, לא תמונה
- [ ] אודיו מוגדר עם "Audio:"
- [ ] "No music" צוין מפורש
- [ ] aspect ratio + duration + resolution צוינו
- [ ] עלות צפויה דווחה למשתמש
- [ ] משתמש אישר

---

🎙️ **הצלחה!**

זכור: הכלים האלה הם **משרתים** של הוויז'ון, לא מחליפים אותו. אם משהו לא יוצא טוב — לא שווה ליצור פעמיים. תעצור, תחשוב, תשנה את הפרומפט, ותיצור שוב.

איכות מעל מהירות. תמיד.
