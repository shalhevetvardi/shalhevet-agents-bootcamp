"""
generate_video.py
=================

יצירת קליפי וידאו דרך **Kling 3.0 Pro** ב-fal.ai (image-to-video).

המעבר מ-Veo (יקר, ~$1-2 לקליפ) ל-Kling (~$0.15-0.30 לקליפ) — חיסכון של 80%+
תוך שמירה על איכות תנועה עדינה ומקצועית.

החשיבה היצירתית מגיעה מהסקיל b-roll-prompter (המוח האחיד).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# CRITICAL: לטעון .env לפני ייבוא של SDKs שיוצרים קליינטים ברמת המודול
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import re
import time
import requests
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

import fal_client
from anthropic import Anthropic

# Anthropic client (לשימוש בהרחבת פרומפט וידאו אם הסטוריבורד לא מכיל אחד)
anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Kling configuration via fal.ai
KLING_ENDPOINT = os.environ.get(
    "KLING_ENDPOINT",
    "fal-ai/kling-video/v3/pro/image-to-video"
)
# Kling supports "5" or "10" seconds. ברירת מחדל: 5s (זול, יספיק לרוב)
KLING_DURATION = os.environ.get("KLING_DURATION", "5")
KLING_ASPECT_RATIO = os.environ.get("KLING_ASPECT_RATIO", "9:16")
# מקסימום משימות במקבילי — fal.ai מוגבל לפי plan, אבל 5 בטוח
KLING_PARALLEL = int(os.environ.get("KLING_PARALLEL", "5"))

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
SKILL_PATH = PROJECT_ROOT / "b-roll-prompter" / "b-roll-prompter.md"


def load_knowledge_file(filename: str) -> str:
    """תאימות לאחור."""
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def load_skill_content() -> str:
    """קורא את b-roll-prompter.md (המוח המאוחד) ומחזיר בלי frontmatter."""
    if not SKILL_PATH.exists():
        return ""
    with open(SKILL_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    if content.startswith('---'):
        try:
            end = content.index('---', 3) + 3
            content = content[end:].strip()
        except ValueError:
            pass
    return content


def extract_ready_video_prompt_from_panel(panel_text: str) -> Optional[str]:
    """
    מנסה לחלץ פרומפט וידאו מוכן מטקסט פאנל (פורמט b-roll-prompter).
    תומך בשני פורמטים:
      1. פרומפט בתוך ```...``` (code fence)
      2. פרומפט כטקסט רגיל אחרי כותרת **🎥 VIDEO PROMPT**, עד הסקציה הבאה

    מחזיר None אם לא נמצא.
    """
    # שיטה 1: code fence — רק אם הוא מופיע אחרי כותרת VIDEO PROMPT
    fence_match = re.search(
        r'(?:VIDEO\s+PROMPT|🎥[^\n]{0,80})\s*\*\*\s*\n+\s*```(?:\w+)?\s*([\s\S]*?)```',
        panel_text,
        re.IGNORECASE
    )
    if fence_match:
        result = fence_match.group(1).strip()
        if result and len(result) > 20:
            return result

    # שיטה 2: טקסט רגיל. נמצא את כותרת ה-VIDEO PROMPT, נקרא עד הסקציה הבאה.
    header_pattern = re.compile(
        r'\*\*\s*🎥?\s*VIDEO\s+PROMPT[^\n*]*\*\*',
        re.IGNORECASE
    )
    header_match = header_pattern.search(panel_text)
    if not header_match:
        return None

    after_header = panel_text[header_match.end():]

    # מחפש את ה-terminator הבא: סקציה אחרת בפאנל הזה או גבול פאנל
    # (References, Duration, Scene, סוגי emoji ידועים, separator, או panel header)
    terminator_pattern = re.compile(
        r'\n\s*(?:'
        r'\*\*\s*📎|'           # **📎 References:**
        r'\*\*\s*📜|'           # **📜 שורת תסריט:**
        r'\*\*\s*🎭|'           # **🎭 ז'אנר:**
        r'\*\*\s*🎨|'           # **🎨 IMAGE PROMPT**
        r'\*\*\s*🛠️|'          # **🛠️ Generation tools**
        r'\*\*\s*Duration|'     # **Duration:**
        r'\*\*\s*References|'   # **References:** (without emoji)
        r'\*\*\s*Scene|'        # **Scene description**
        r'-{3,}\s*$|'           # --- separator
        r'#{2,}'                # ## or ### (next panel)
        r')',
        re.MULTILINE
    )
    term_match = terminator_pattern.search(after_header)

    if term_match:
        prompt_body = after_header[:term_match.start()]
    else:
        prompt_body = after_header

    prompt_body = prompt_body.strip()
    # ניקוי code fences שעלולים להיות בתוך הטקסט
    prompt_body = re.sub(r'^```\w*\s*\n?', '', prompt_body, flags=re.MULTILINE)
    prompt_body = re.sub(r'\n```\s*$', '', prompt_body)
    prompt_body = prompt_body.strip()

    if prompt_body and len(prompt_body) > 30:
        return prompt_body

    return None


def select_panels_for_video(panels: List[dict]) -> List[dict]:
    """
    בוחר את הפאנלים המתאימים לוידאו.

    בעבר: מקסימום 3-5 בגלל יוקר Veo.
    עכשיו: כל הפאנלים שאינם טיפוגרפיים — Kling זול מספיק כדי לכסות הכל.
    """
    return [p for p in panels if not p.get('is_typography', False)]


def parse_panels_from_storyboard(storyboard: str) -> List[dict]:
    """
    מנתח את הסטוריבורד ומחזיר רשימת פאנלים.
    """
    panels = []

    panel_pattern = re.compile(
        r'#{2,4}\s*\**\s*PANEL\s*(\d+[A-Z]?)\s*\**\s*[—\-]?\s*(.+?)(?=#{2,4}\s*\**\s*PANEL|\Z)',
        re.DOTALL | re.IGNORECASE
    )

    for match in panel_pattern.finditer(storyboard):
        panel_num = match.group(1)
        panel_content = match.group(2).strip()

        is_typography = any(keyword in panel_content for keyword in [
            'טיפוגרפיה', 'typography', 'טקסט על מסך', 'on-screen text',
            'Full-frame typography'
        ])

        panels.append({
            'number': panel_num,
            'content': panel_content,
            'is_typography': is_typography
        })

    return panels


def expand_panel_to_video_prompt(panel: dict) -> str:
    """
    מחזיר פרומפט וידאו לפאנל.

    1. אם הסטוריבורד נכתב ע"י המוח החדש (b-roll-prompter), הפרומפט כבר קיים
       בתוך הפאנל — מחלצים ומחזירים.
    2. אם לא — מרחיבים עם המוח של b-roll-prompter כ-system prompt.
    """
    extracted = extract_ready_video_prompt_from_panel(panel['content'])
    if extracted:
        return extracted

    skill_brain = load_skill_content()

    system = f"""You are the b-roll-prompter creative brain, generating a VIDEO prompt
for image-to-video generation. The first frame is already provided as an image —
your job is to describe what HAPPENS over the clip duration.

==== THE CREATIVE BRAIN (b-roll-prompter skill) ====

{skill_brain}

==== END OF CREATIVE BRAIN ====

==== YOUR SPECIFIC TASK ====

Generate a video prompt that describes ONLY motion (the still frame is provided).

CRITICAL RULES:
1. Do NOT describe what the image shows — that's the first frame.
2. Describe ONLY: camera movement, subject action, environmental motion, audio.
3. Use the 5-second event beat structure.
4. State the dramatic event at a SPECIFIC second.
5. Always include separate "Audio:" block with timed sound events.
6. Always end with "No music. No voiceover." unless context requires otherwise.

Output ONLY the prompt text — no preamble, no commentary."""

    user = f"""Convert this storyboard panel into a video prompt for Kling 3.0 image-to-video.

==== PANEL ====
{panel['content']}

Output the video prompt now."""

    response = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )

    return response.content[0].text.strip()


def find_image_for_panel(panel_num: str, image_paths: List[Path]) -> Optional[Path]:
    """מוצא תמונה אחת לפאנל לפי מספר (תאימות לאחור)."""
    for path in image_paths:
        if f"panel_{panel_num}" in path.name or f"panel_{panel_num.lstrip('0')}" in path.name:
            return path
    return None


def find_versions_for_panel(panel_num: str, image_paths: List[Path]) -> Dict[str, Path]:
    """
    מחזיר {"v1": path, "v2": path} לפאנל. ריק אם לא נמצאו.

    מחפש קבצים בפורמט panel_X_v1.png ו-panel_X_v2.png.
    """
    versions = {}
    for path in image_paths:
        # match panel_3_v1.png or panel_03_v2.png
        m = re.match(rf'^panel_{panel_num}_v(\d+)\.', path.name)
        if not m:
            m = re.match(rf'^panel_{panel_num.lstrip("0")}_v(\d+)\.', path.name)
        if m:
            v = m.group(1)
            versions[f"v{v}"] = path
    return versions


def generate_video_for_panel(panel: dict, image_path: Path, output_dir: Path,
                              version: Optional[str] = None) -> Optional[Path]:
    """
    מייצר קליפ וידאו אחד לפאנל ספציפי באמצעות Kling 3.0 Pro דרך fal.ai.

    Args:
        panel: dict הפאנל
        image_path: ה-first frame
        output_dir: תיקיית פלט
        version: אופציונלי, "v1" או "v2". אם None — שם הקובץ הוא clip_panel_X.mp4.

    תהליך:
    1. מקבל פרומפט וידאו (מהסטוריבורד או מ-Claude)
    2. מעלה את ה-first frame ל-fal storage
    3. שולח ל-Kling דרך fal_client
    4. ממתין לתוצאה
    5. מוריד את הוידאו
    """
    panel_num = panel['number']
    version_suffix = f"_{version}" if version else ""
    version_marker = f" [{version}]" if version else ""
    print(f"   🎥 פאנל {panel_num}{version_marker}...")

    if not image_path or not image_path.exists():
        print(f"      ❌ לא נמצאה תמונת first frame")
        return None

    # שלב 1: קבלת/הרחבת פרומפט וידאו
    video_prompt = expand_panel_to_video_prompt(panel)

    # שלב 2: העלאת התמונה ל-fal storage
    try:
        print(f"      ☁️  מעלה תמונה ל-fal storage...")
        image_url = fal_client.upload_file(str(image_path))
    except Exception as e:
        print(f"      ❌ העלאה נכשלה: {e}")
        return None

    # שלב 3: שליחה ל-Kling
    print(f"      🚀 שולח ל-Kling 3.0 Pro (משך: {KLING_DURATION}s)...")

    try:
        handler = fal_client.submit(
            KLING_ENDPOINT,
            arguments={
                "prompt": video_prompt,
                "image_url": image_url,
                "duration": KLING_DURATION,
                "aspect_ratio": KLING_ASPECT_RATIO,
            }
        )
    except Exception as e:
        print(f"      ❌ שליחה ל-Kling נכשלה: {e}")
        return None

    # שלב 4: המתנה לתוצאה
    try:
        result = handler.get()
    except Exception as e:
        print(f"      ❌ Kling החזיר שגיאה: {e}")
        return None

    # שלב 5: חילוץ URL והורדה
    video_obj = result.get("video", {}) if isinstance(result, dict) else {}
    video_url = video_obj.get("url") if isinstance(video_obj, dict) else None

    if not video_url:
        print(f"      ❌ Kling לא החזיר video URL: {result}")
        return None

    video_path = output_dir / f"clip_panel_{panel_num}{version_suffix}.mp4"
    try:
        response = requests.get(video_url, timeout=180)
        response.raise_for_status()
        with open(video_path, 'wb') as f:
            f.write(response.content)
    except Exception as e:
        print(f"      ❌ הורדה נכשלה: {e}")
        return None

    print(f"      ✅ {video_path.name} ({len(response.content):,} bytes)")
    return video_path


def estimate_cost(num_videos: int) -> str:
    """
    אומדן עלות לפי Kling Pro 3.0 ב-fal.ai.
    תמחור משוער: ~$0.029 לשניה.
      - 5s clip: ~$0.15
      - 10s clip: ~$0.30
    """
    cost_per_clip = 0.15 if KLING_DURATION == "5" else 0.30
    total = num_videos * cost_per_clip
    return f"~${total:.2f} ({num_videos} × ~${cost_per_clip:.2f})"


def generate_videos_for_storyboard(
    storyboard: str,
    image_paths: List[Path],
    videos_dir: Path
) -> List[Path]:
    """
    מייצר את כל קליפי הוידאו לפי הסטוריבורד באמצעות Kling 3.0 Pro.

    משימות רצות במקבילי דרך ThreadPoolExecutor — fal.ai תומך בכך וזה מקטין
    משמעותית את זמן ההפקה הכולל.

    Args:
        storyboard: התוכן המלא של הסטוריבורד
        image_paths: רשימת נתיבי תמונות שכבר נוצרו
        videos_dir: תיקיית פלט לוידאו

    Returns:
        רשימת נתיבי הוידאו שנוצרו
    """
    # אימות מפתח fal
    if not os.environ.get("FAL_KEY"):
        print("   ❌ חסר FAL_KEY ב-.env — אי אפשר להריץ Kling")
        return []

    # שלב 1: ניתוח הסטוריבורד ובחירת פאנלים
    all_panels = parse_panels_from_storyboard(storyboard)
    video_panels = select_panels_for_video(all_panels)

    print(f"\n   📋 זוהו {len(all_panels)} פאנלים, {len(video_panels)} מתאימים לוידאו (כולם פרט לטיפוגרפיים)")

    # שלב 2: בנה task list לפי v1/v2 (אם יש), אחרת fallback ל-תמונה אחת לפאנל
    tasks = []  # list of (panel, image_path, version_or_None)
    panels_with_versions_count = 0
    panels_with_single_count = 0

    for panel in video_panels:
        versions = find_versions_for_panel(panel['number'], image_paths)
        if versions:
            # מצב חדש: v1 + v2
            for v_label in sorted(versions.keys()):
                tasks.append((panel, versions[v_label], v_label))
            panels_with_versions_count += 1
        else:
            # fallback: תמונה אחת
            single = find_image_for_panel(panel['number'], image_paths)
            if single:
                tasks.append((panel, single, None))
                panels_with_single_count += 1
            else:
                print(f"   ⚠️  פאנל {panel['number']}: אין תמונה, מדלג")

    if not tasks:
        print("   ❌ אין תמונות זמינות לאף פאנל")
        return []

    total_clips = len(tasks)

    # שלב 3: הצגת תקציר ובקשת אישור
    print(f"\n   📊 סיכום משימות:")
    if panels_with_versions_count:
        print(f"      • {panels_with_versions_count} פאנלים עם 2 גרסאות (v1+v2)")
    if panels_with_single_count:
        print(f"      • {panels_with_single_count} פאנלים עם תמונה אחת")
    print(f"      • סה\"כ {total_clips} קליפים")

    print(f"\n   💰 עלות מוערכת: {estimate_cost(total_clips)}")
    print(f"   🎬 מודל: Kling 3.0 Pro דרך fal.ai")
    print(f"   📐 פרמטרים: {KLING_DURATION}s, {KLING_ASPECT_RATIO}")
    print(f"   ⚡ {KLING_PARALLEL} משימות במקבילי")
    print(f"   ⏱️  זמן משוער: ~{max(2, total_clips // KLING_PARALLEL * 2)} דקות")

    print(f"\n   הפאנלים שיווצרו לוידאו:")
    seen_panels = set()
    for panel, _, _ in tasks:
        if panel['number'] not in seen_panels:
            seen_panels.add(panel['number'])
            first_line = panel['content'].split('\n')[0][:80]
            print(f"      פאנל {panel['number']}: {first_line}...")

    proceed = input("\n   האם להמשיך? (y/n): ").strip().lower()
    if proceed != 'y':
        print("   👋 דילוג על שלב הוידאו")
        return []

    # שלב 4: יצירת וידאו במקבילי
    print(f"\n   🚀 מפעיל {total_clips} משימות Kling במקבילי...")
    print(f"   (תקבלי סטטוס בסיום של כל קליפ, לא בסדר.)\n")

    video_paths = []
    with ThreadPoolExecutor(max_workers=KLING_PARALLEL) as executor:
        futures = {}
        for panel, image_path, version in tasks:
            future = executor.submit(
                generate_video_for_panel, panel, image_path, videos_dir, version
            )
            label = f"{panel['number']}{f'/{version}' if version else ''}"
            futures[future] = label

        for future in as_completed(futures):
            label = futures[future]
            try:
                result = future.result()
                if result:
                    video_paths.append(result)
            except Exception as e:
                print(f"   ❌ {label} נכשל: {e}")

    print(f"\n   📊 סיכום: {len(video_paths)}/{total_clips} קליפים נוצרו בהצלחה")
    return video_paths


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) > 2:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            storyboard = f.read()
        images_dir = Path(sys.argv[2])
        image_paths = list(images_dir.glob("panel_*.png"))
        output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("./test_videos")
        output_dir.mkdir(exist_ok=True)
        result = generate_videos_for_storyboard(storyboard, image_paths, output_dir)
        print(f"\nנוצרו {len(result)} קליפי וידאו")
    else:
        print("Usage: python generate_video.py <storyboard_path> <images_dir> [<output_dir>]")
