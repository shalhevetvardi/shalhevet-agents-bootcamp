"""
generate_storyboard.py
======================

יצירת storyboard מפורט מתוך טיזר נבחר או טיזר מוכן.

החשיבה היצירתית מגיעה מהסקיל b-roll-prompter — המוח האחיד של המערכת.
הסקיל הוא מקור האמת. אם תעדכני את הסקיל, גם הפייפליין יישר קו אוטומטית.
"""

import os
from pathlib import Path
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Claude model — defaults to Sonnet 4.6, override via CLAUDE_MODEL env var
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
SKILL_PATH = PROJECT_ROOT / "b-roll-prompter" / "b-roll-prompter.md"


def load_knowledge_file(filename: str) -> str:
    """טוען קובץ ידע מתיקיית knowledge/. נשמר לתאימות לאחור."""
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def load_skill_content() -> str:
    """
    קורא את b-roll-prompter.md ומחזיר את התוכן בלי ה-YAML frontmatter.

    זה ה"מוח" של המערכת. כל המודולים בפייפליין שעושים חשיבה יצירתית
    משתמשים בקובץ הזה כ-system prompt.

    Returns:
        תוכן הסקיל (markdown) בלי frontmatter.
    """
    if not SKILL_PATH.exists():
        raise FileNotFoundError(
            f"קובץ הסקיל לא נמצא: {SKILL_PATH}\n"
            "הסקיל הוא המוח של הפייפליין — בלעדיו אי אפשר לעבוד."
        )

    with open(SKILL_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # הסרת YAML frontmatter (בין ---...--- בתחילת הקובץ)
    if content.startswith('---'):
        try:
            end = content.index('---', 3) + 3
            content = content[end:].strip()
        except ValueError:
            pass  # אין סוגר ל-frontmatter, מחזירים כמו שהוא

    return content


def load_example_storyboard() -> str:
    path = EXAMPLES_DIR / "claude-code-episode" / "output" / "storyboard.md"
    if not path.exists():
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _build_creative_system_prompt() -> str:
    """
    בונה system prompt מבוסס על הסקיל. משותף לשתי הפונקציות.
    """
    skill_brain = load_skill_content()

    return f"""You are the b-roll-prompter creative brain, operating inside an automated pipeline.

The complete creative methodology is below. Read it carefully — it is the source of truth
for HOW to think about converting a script into a reel storyboard. Your output must
follow it exactly, including:

- The two-phase workflow (Macro Plan first, then Panels)
- Camera-First geometric constraints (no "POV"/"OTS" — always explicit camera position)
- Genre selection per panel from the genre library
- Recurring objects with state changes
- Color as moral signal (real brand color vs faked/cheap variant)
- 5-second event beat in every video clip
- Brand woven through diegetic objects (text on screens/robots/boxes — never as overlay)
- Hebrew typography is FORBIDDEN. English sentences are FORBIDDEN. Only brand/product names allowed in-scene.
- Specific lighting recipes (named, not generic)
- Anti-reference for cliche avoidance (specific to each archetype)
- CTA panel = visual scene with explicit negative space spec for CapCut text overlay

==== THE CREATIVE BRAIN (b-roll-prompter skill) ====

{skill_brain}

==== END OF CREATIVE BRAIN ===="""


def generate_storyboard(teasers_content: str, chosen_teaser_num: int, episode_content: str) -> str:
    """
    מייצר storyboard מפורט לטיזר הנבחר מתוך 5 הטיזרים שיוצרו מתמליל פודקאסט.

    Args:
        teasers_content: התוכן של 5 הטיזרים
        chosen_teaser_num: מספר הטיזר הנבחר (1-5)
        episode_content: התוכן המלא של הפרק (לקונטקסט)

    Returns:
        מסמך markdown עם תכנון מקרו ופאנלים מלאים (פרומפטי תמונה ווידאו).
    """
    system_prompt = _build_creative_system_prompt()

    user_prompt = f"""Below are 5 teaser ideas. The user has chosen teaser #{chosen_teaser_num}.

Your job: take the chosen teaser and produce a complete prompt package following
the b-roll-prompter creative brain.

OUTPUT REQUIREMENTS:
1. Start with the brand identification line.
2. Then the Macro Plan section (Acts, Recurring Objects, Color Moral Signal,
   Camera Arc, Genre per Panel) — THIS IS MANDATORY before any panel.
3. Then 8-13 panels, each with:
   - Script line it corresponds to
   - Genre
   - Scene description in Hebrew
   - Full IMAGE PROMPT in English (Camera-First, ready to paste)
   - Full VIDEO PROMPT in English (image-to-video, 8s, with explicit 4-6s event,
     Audio block, "No music. No voiceover.", aspect ratio + duration + resolution)
   - References decision (include_character_ref / include_location_ref) with reasoning
   - Duration
4. Visual CTA panel at the end with EXPLICIT negative space spec.
5. Production summary table.

Output in Hebrew markdown. Image and video prompts themselves stay in English.

==== TEASERS ====
{teasers_content}

==== EPISODE CONTEXT (for reference only) ====
{episode_content[:5000]}"""

    print(f"   🎨 שולח לקלוד ליצירת storyboard לטיזר {chosen_teaser_num} (מוח: b-roll-prompter)...")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=12000,  # הוגדל כדי לאפשר macro plan + 8-13 פאנלים מלאים
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    return response.content[0].text


def generate_storyboard_from_teaser(teaser_text: str) -> str:
    """
    מייצר storyboard מפורט מתוך טיזר/תסריט ריל מוכן (קלט קצר).

    שימושי כשהמשתמשת מעלה תסריט ריל ידני בלי מעבר דרך פודקאסט/חילוץ ציטוטים.

    Args:
        teaser_text: הטקסט של הטיזר/תסריט הריל

    Returns:
        מסמך markdown עם תכנון מקרו ופאנלים מלאים.
    """
    system_prompt = _build_creative_system_prompt()

    user_prompt = f"""Below is a ready reel script. Take it and produce a complete prompt
package following the b-roll-prompter creative brain.

OUTPUT REQUIREMENTS:
1. Start with the brand identification line.
2. Then the Macro Plan section (Acts, Recurring Objects, Color Moral Signal,
   Camera Arc, Genre per Panel) — THIS IS MANDATORY before any panel.
3. Then 8-13 panels, each with:
   - Script line it corresponds to
   - Genre
   - Scene description in Hebrew
   - Full IMAGE PROMPT in English (Camera-First, ready to paste)
   - Full VIDEO PROMPT in English (image-to-video, 8s, with explicit 4-6s event,
     Audio block, "No music. No voiceover.", aspect ratio + duration + resolution)
   - References decision (include_character_ref / include_location_ref) with reasoning
   - Duration
4. Visual CTA panel at the end with EXPLICIT negative space spec.
5. Production summary table.

Output in Hebrew markdown. Image and video prompts themselves stay in English.

==== REEL SCRIPT ====
{teaser_text}"""

    print("   🎨 שולח לקלוד ליצירת storyboard מתסריט ריל (מוח: b-roll-prompter)...")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=12000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )

    return response.content[0].text


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) > 3:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            teasers = f.read()
        teaser_num = int(sys.argv[2])
        with open(sys.argv[3], 'r', encoding='utf-8') as f:
            episode = f.read()
        result = generate_storyboard(teasers, teaser_num, episode)
        print(result)
    elif len(sys.argv) == 3 and sys.argv[1] == "--from-teaser":
        with open(sys.argv[2], 'r', encoding='utf-8') as f:
            teaser = f.read()
        result = generate_storyboard_from_teaser(teaser)
        print(result)
    else:
        print("Usage:")
        print("  python generate_storyboard.py <teasers_path> <teaser_num> <episode_path>")
        print("  python generate_storyboard.py --from-teaser <teaser_path>")
