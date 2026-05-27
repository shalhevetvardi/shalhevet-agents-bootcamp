"""
generate_shot_list.py
=====================

יצירת מסמך shot-list.md ידידותי לעריכה.

לכל שוט:
- מספר + טווח זמן מצטבר
- שורת התסריט המתאימה
- תיאור ויזואלי קצר בעברית
- קבצי v1 (ראשי) + v2 (חלופה) — אם קיימים
- משך מומלץ
- הערות

מטרה: שלהבת תוכל לפתוח את המסמך ב-CapCut, להעיף מבט, ולדעת בדיוק איזה קובץ להניח
על איזה חלק של הוויסאובר.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from anthropic import Anthropic

anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


# ============================================================
# Panel parsing (mirror of other modules)
# ============================================================

def parse_panels_from_storyboard(storyboard: str) -> List[Dict]:
    """כמו במודולים האחרים."""
    panels = []
    panel_pattern = re.compile(
        r'#{2,4}\s*\**\s*PANEL\s*(\d+[A-Z]?)\s*\**\s*[—\-]?\s*(.+?)(?=#{2,4}\s*\**\s*PANEL|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    for match in panel_pattern.finditer(storyboard):
        panel_num = match.group(1)
        panel_content = match.group(2).strip()
        is_typography = any(k in panel_content for k in [
            'טיפוגרפיה', 'typography', 'טקסט על מסך', 'on-screen text',
            'Full-frame typography'
        ])
        is_personal = bool(re.search(r'🪞\s*PERSONAL\s*PANEL', panel_content, re.IGNORECASE))

        # חלץ panel name (אחרי המקף)
        name_match = re.match(r'(.+?)(?:\s*🪞|\Z)', panel_content.split('\n')[0] if panel_content else '')
        panel_name = name_match.group(1).strip().strip('"').strip() if name_match else ''

        panels.append({
            'number': panel_num,
            'content': panel_content,
            'name': panel_name,
            'is_typography': is_typography,
            'is_personal': is_personal,
        })
    return panels


def extract_field(panel_content: str, field_pattern: str) -> Optional[str]:
    """מחלץ ערך של שדה מובנה מהפאנל."""
    m = re.search(field_pattern, panel_content, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("*").strip()
    return None


def extract_panel_name(panel_content: str, panel_number: str) -> str:
    """מחלץ את שם הפאנל מהכותרת — הטקסט אחרי 'PANEL X — '."""
    # Look at the very first line which might have already been split off by parse_panels
    # Actually parse_panels already strips the PANEL X header. Try to find name elsewhere.
    # The original heading was "### **PANEL X** — שם", but content starts after that.
    # Look for clue in first 100 chars
    return ""


def extract_script_line(panel_content: str) -> str:
    """מחלץ את שורת התסריט מהפאנל."""
    # Try the labeled format
    m = re.search(
        r'\*\*\s*📜?[^*]*תסריט[^*]*\*\*\s*\*?["׳״“”](.+?)["׳״“”]',
        panel_content,
        re.IGNORECASE | re.DOTALL
    )
    if m:
        return m.group(1).strip()
    # Fallback: any quoted line near 📜
    m = re.search(r'📜[^\n]*\n+\s*\*?["“”](.+?)["“”]', panel_content)
    if m:
        return m.group(1).strip()
    return ""


def extract_scene_description(panel_content: str) -> str:
    """מחלץ את תיאור הסצנה בעברית מהפאנל."""
    m = re.search(
        r'\*\*\s*Scene\s+description[^*]*\*\*\s*\n+([\s\S]+?)(?=\n\s*\*\*|\n\s*```|\Z)',
        panel_content,
        re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    return ""


def extract_duration_seconds(panel_content: str) -> Optional[float]:
    """מחלץ את משך הפאנל בשניות."""
    m = re.search(r'\*\*\s*Duration:?\s*\*\*\s*(\d+(?:\.\d+)?)\s*s', panel_content, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # Sometimes duration appears as plain text "Duration: 3s"
    m = re.search(r'Duration:?\s*(\d+(?:\.\d+)?)\s*s', panel_content, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def extract_genre(panel_content: str) -> str:
    """מחלץ את הז'אנר."""
    m = re.search(
        r'\*\*\s*🎭?[^*]*ז\'?אנר[^*]*\*\*\s*\*?(.+?)(?:\n|$)',
        panel_content,
        re.IGNORECASE
    )
    if m:
        return m.group(1).strip().strip('*')
    return ""


# ============================================================
# File detection (v1/v2 + clips)
# ============================================================

def find_files_for_panel(panel_num: str, images_dir: Path, videos_dir: Path) -> Dict[str, Optional[Path]]:
    """
    מוצא את כל הקבצים הזמינים לפאנל:
    - panel_X_v1.png, panel_X_v2.png (הגרסאות החדשות)
    - panel_X.png (הגרסה הישנה — fallback)
    - clip_panel_X_v1.mp4, clip_panel_X_v2.mp4
    - clip_panel_X.mp4 (fallback)
    """
    files: Dict[str, Optional[Path]] = {
        'image_v1': None, 'image_v2': None, 'image_single': None,
        'video_v1': None, 'video_v2': None, 'video_single': None,
    }

    if images_dir and images_dir.exists():
        for ver in ['v1', 'v2']:
            p = images_dir / f"panel_{panel_num}_{ver}.png"
            if p.exists():
                files[f'image_{ver}'] = p
        single = images_dir / f"panel_{panel_num}.png"
        if single.exists():
            files['image_single'] = single

    if videos_dir and videos_dir.exists():
        for ver in ['v1', 'v2']:
            p = videos_dir / f"clip_panel_{panel_num}_{ver}.mp4"
            if p.exists():
                files[f'video_{ver}'] = p
        single = videos_dir / f"clip_panel_{panel_num}.mp4"
        if single.exists():
            files['video_single'] = single

    return files


# ============================================================
# Markdown rendering
# ============================================================

def format_time(seconds: float) -> str:
    """ממיר שניות ל-mm:ss."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def get_reel_title_from_storyboard(storyboard: str) -> str:
    """שולה את כותרת הריל מהסטוריבורד."""
    m = re.search(r'^#\s+[^\n]*?ריל\s+["׳״“”]?(.+?)["׳״“”]?\s*$', storyboard, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r'^#\s+(.+?)$', storyboard, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "ריל"


def render_shot(
    shot_num: int,
    panel: Dict,
    cumulative_start: float,
    files: Dict[str, Optional[Path]],
) -> str:
    """ממיר פאנל בודד לבלוק SHOT ב-shot list."""
    duration = extract_duration_seconds(panel['content']) or 3.0
    cumulative_end = cumulative_start + duration

    script_line = extract_script_line(panel['content'])
    scene_desc = extract_scene_description(panel['content'])
    genre = extract_genre(panel['content'])

    # קיצור תיאור הסצנה (לפעמים ארוך מאוד)
    if len(scene_desc) > 250:
        scene_desc = scene_desc[:247] + '...'

    md = []
    title = f"## SHOT {shot_num}"
    if panel.get('is_personal'):
        title += "  🪞"
    md.append(title)

    md.append(f"**זמן:** {format_time(cumulative_start)} – {format_time(cumulative_end)}  ({duration:g}s)")

    if script_line:
        md.append(f"**שורת תסריט:** *\"{script_line}\"*")

    if genre:
        md.append(f"**ז'אנר:** {genre}")

    if scene_desc:
        md.append(f"**ויזואל:** {scene_desc}")

    # Files
    md.append("**קבצים:**")
    has_v1 = files.get('image_v1') or files.get('video_v1')
    has_v2 = files.get('image_v2') or files.get('video_v2')

    if has_v1 or has_v2:
        if has_v1:
            parts = []
            if files.get('image_v1'):
                parts.append(f"`{files['image_v1'].name}`")
            if files.get('video_v1'):
                parts.append(f"`{files['video_v1'].name}`")
            md.append(f"- 🎬 **ראשי (v1):** {' + '.join(parts)}")
        if has_v2:
            parts = []
            if files.get('image_v2'):
                parts.append(f"`{files['image_v2'].name}`")
            if files.get('video_v2'):
                parts.append(f"`{files['video_v2'].name}`")
            md.append(f"- 🎬 **חלופה (v2):** {' + '.join(parts)}")
    else:
        # fallback למצב ישן (תמונה/קליפ אחד)
        parts = []
        if files.get('image_single'):
            parts.append(f"`{files['image_single'].name}`")
        if files.get('video_single'):
            parts.append(f"`{files['video_single'].name}`")
        if parts:
            md.append(f"- 🎬 {' + '.join(parts)}")
        else:
            md.append("- ⚠️ אין קבצים זמינים")

    md.append("\n---\n")
    return "\n".join(md)


def generate_shot_list(
    storyboard: str,
    images_dir: Path,
    videos_dir: Path,
    output_file: Path,
) -> Path:
    """
    יוצר shot-list.md מבוסס על הסטוריבורד והקבצים שיש בתיקיות.

    Returns:
        path לקובץ שנכתב.
    """
    panels = parse_panels_from_storyboard(storyboard)
    relevant = [p for p in panels if not p['is_typography']]

    title = get_reel_title_from_storyboard(storyboard)

    md_parts = []
    md_parts.append(f"# רשימת שוטים — {title}")
    md_parts.append("")
    md_parts.append("> מפת עריכה לטיימליין שלך ב-CapCut.")
    md_parts.append("> לכל שוט: שורת התסריט, תיאור ויזואלי, וקבצים זמינים (v1 ראשי + v2 חלופה).")
    md_parts.append("> 🪞 = פאנל אישי (שלהבת בקאדר).")
    md_parts.append("")
    md_parts.append("---")
    md_parts.append("")

    cumulative_time = 0.0
    total_duration = 0.0
    panels_with_versions = 0
    panels_with_single = 0

    for i, panel in enumerate(relevant, start=1):
        files = find_files_for_panel(panel['number'], images_dir, videos_dir)
        if files.get('image_v1') or files.get('image_v2'):
            panels_with_versions += 1
        elif files.get('image_single'):
            panels_with_single += 1

        block = render_shot(i, panel, cumulative_time, files)
        md_parts.append(block)

        duration = extract_duration_seconds(panel['content']) or 3.0
        cumulative_time += duration
        total_duration += duration

    # סיכום בסוף
    md_parts.append("\n## 📊 סיכום\n")
    md_parts.append(f"- **סך שוטים:** {len(relevant)}")
    md_parts.append(f"- **משך כולל:** {format_time(total_duration)} ({total_duration:g}s)")
    if panels_with_versions:
        md_parts.append(f"- **פאנלים עם 2 גרסאות:** {panels_with_versions}")
    if panels_with_single:
        md_parts.append(f"- **פאנלים עם תמונה אחת:** {panels_with_single}")
    md_parts.append("")
    md_parts.append("**טיפ ל-CapCut:** הניחי את גרסת v1 כברירת מחדל בטיימליין. אם משהו לא עובד —")
    md_parts.append("תחליפי לגרסת v2 שכבר מוכנה לצדה. אין צורך לחזור ולייצר.")

    # כתיבה
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_parts))

    return output_file


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 3:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            sb = f.read()
        images_dir = Path(sys.argv[2])
        videos_dir = Path(sys.argv[3])
        output_file = Path(sys.argv[4]) if len(sys.argv) > 4 else images_dir.parent / "shot-list.md"
        result = generate_shot_list(sb, images_dir, videos_dir, output_file)
        print(f"shot-list נשמר: {result}")
    else:
        print("Usage: python generate_shot_list.py <storyboard> <images_dir> <videos_dir> [<output_file>]")
