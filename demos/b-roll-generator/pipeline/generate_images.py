"""
generate_images.py
==================

יצירת תמונות סטילס באמצעות **Flux** ב-fal.ai.

מעבר מ-Nano Banana (Gemini) ל-Flux (fal.ai) כי:
- תומך native ב-9:16 (לא תלוי בפרומפט)
- תומך בלורה אישית (לפאנלים של שלהבת)
- אותה פלטפורמה כמו Kling — נוח לעבודה אחידה

החשיבה היצירתית מגיעה מהסקיל b-roll-prompter (המוח האחיד).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# CRITICAL: לטעון .env לפני ייבוא של SDKs שיוצרים קליינטים
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import re
import json
import requests
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import fal_client
from anthropic import Anthropic

# Anthropic client (להרחבת פרומפט אם הסטוריבורד לא מכיל אחד)
anthropic_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Flux configuration
FLUX_ENDPOINT = os.environ.get("FLUX_ENDPOINT", "fal-ai/flux-pro/v1.1")
FLUX_LORA_ENDPOINT = os.environ.get("FLUX_LORA_ENDPOINT", "fal-ai/flux-lora")
FLUX_IMAGE_SIZE = os.environ.get("FLUX_IMAGE_SIZE", "portrait_16_9")  # 9:16 native
FLUX_INFERENCE_STEPS = int(os.environ.get("FLUX_INFERENCE_STEPS", "28"))
FLUX_PARALLEL = int(os.environ.get("FLUX_PARALLEL", "5"))

# Shalhevet's LoRA (לפאנלים אישיים)
SHALHEVET_LORA_URL = os.environ.get("SHALHEVET_LORA_URL", "")
SHALHEVET_LORA_TRIGGER = os.environ.get("SHALHEVET_LORA_TRIGGER", "shalhevet")

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
SKILL_PATH = PROJECT_ROOT / "b-roll-prompter" / "b-roll-prompter.md"


# ============================================================
# Skill content loader (המוח המאוחד)
# ============================================================

def load_knowledge_file(filename: str) -> str:
    """תאימות לאחור."""
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def load_skill_content() -> str:
    """קורא את b-roll-prompter.md ומחזיר בלי frontmatter."""
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


# ============================================================
# Panel parsing & prompt extraction
# ============================================================

def is_personal_panel(panel_text: str) -> bool:
    """מזהה פאנל אישי (שלהבת בקאדר) לפי הסימון 🪞 PERSONAL PANEL."""
    return bool(re.search(r'🪞\s*PERSONAL\s*PANEL', panel_text, re.IGNORECASE))


def extract_ready_prompts_from_panel(panel_text: str) -> dict:
    """
    מחלץ פרומפטים מוכנים מטקסט פאנל (פורמט b-roll-prompter).
    תומך גם ב-code fences וגם בטקסט רגיל אחרי כותרת.
    """
    result = {}

    # ---- IMAGE PROMPT ----
    # שיטה 1: code fence
    fence_match = re.search(
        r'(?:IMAGE\s+PROMPT|🎨[^\n]{0,80})\s*\*\*\s*\n+\s*```(?:\w+)?\s*([\s\S]*?)```',
        panel_text,
        re.IGNORECASE
    )
    img_prompt = None
    if fence_match:
        candidate = fence_match.group(1).strip()
        if candidate and len(candidate) > 30:
            img_prompt = candidate

    # שיטה 2: טקסט רגיל אחרי כותרת
    if not img_prompt:
        header_pattern = re.compile(
            r'\*\*\s*🎨?\s*IMAGE\s+PROMPT[^\n*]*\*\*',
            re.IGNORECASE
        )
        header_match = header_pattern.search(panel_text)
        if header_match:
            after = panel_text[header_match.end():]
            terminator = re.compile(
                r'\n\s*(?:'
                r'\*\*\s*🎥|'
                r'\*\*\s*📎|'
                r'\*\*\s*🛠️|'
                r'\*\*\s*Duration|'
                r'\*\*\s*References|'
                r'\*\*\s*🎭|'
                r'-{3,}\s*$|'
                r'#{2,}'
                r')',
                re.MULTILINE
            )
            term_match = terminator.search(after)
            body = after[:term_match.start()] if term_match else after
            body = body.strip()
            body = re.sub(r'^```\w*\s*\n?', '', body, flags=re.MULTILINE)
            body = re.sub(r'\n```\s*$', '', body)
            body = body.strip()
            if body and len(body) > 30:
                img_prompt = body

    if img_prompt:
        result['image_prompt'] = img_prompt

    # ---- References decisions ----
    char_ref_match = re.search(
        r'include_character_ref:\s*(כן|לא|true|false|yes|no)',
        panel_text,
        re.IGNORECASE
    )
    if char_ref_match:
        val = char_ref_match.group(1).lower()
        result['include_character_ref'] = val in ('כן', 'true', 'yes')

    loc_ref_match = re.search(
        r'include_location_ref:\s*(כן|לא|true|false|yes|no)',
        panel_text,
        re.IGNORECASE
    )
    if loc_ref_match:
        val = loc_ref_match.group(1).lower()
        result['include_location_ref'] = val in ('כן', 'true', 'yes')

    return result


def parse_panels_from_storyboard(storyboard: str) -> List[Dict]:
    """מנתח את הסטוריבורד ומחזיר רשימת פאנלים."""
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
        panels.append({
            'number': panel_num,
            'content': panel_content,
            'is_typography': is_typography,
            'is_personal': is_personal_panel(panel_content),
        })
    return panels


# ============================================================
# Prompt expansion (fallback if storyboard lacks ready prompt)
# ============================================================

def expand_panel_to_image_prompt(panel_text: str) -> dict:
    """
    Backward-compatible function. אם הפאנל מכיל פרומפט מוכן — מחזיר אותו.
    אחרת מרחיב באמצעות הסקיל.
    """
    extracted = extract_ready_prompts_from_panel(panel_text)
    if 'image_prompt' in extracted:
        return {
            'prompt': extracted['image_prompt'],
            'include_character_ref': extracted.get('include_character_ref', False),
            'include_location_ref': extracted.get('include_location_ref', False),
            'reasoning': 'extracted from b-roll-prompter storyboard',
        }

    skill_brain = load_skill_content()
    system = f"""You are the b-roll-prompter creative brain, generating an image prompt
for a single panel within a larger reel storyboard.

==== THE CREATIVE BRAIN (b-roll-prompter skill) ====

{skill_brain}

==== END OF CREATIVE BRAIN ====

==== YOUR SPECIFIC TASK ====

Convert the panel description into a complete IMAGE prompt (English, 250-400
words, ready to paste into Flux / Nano Banana / Midjourney).

Return ONLY valid JSON:

{{
  "include_character_ref": true | false,
  "include_location_ref": true | false,
  "reasoning": "one short sentence",
  "prompt": "the full English image prompt"
}}"""

    user = f"==== PANEL ====\n{panel_text}\n\nReturn the JSON object."

    response = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```\s*$', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError(f"Claude לא החזיר JSON תקין: {raw[:300]}") from e


# ============================================================
# Flux generation (fal.ai)
# ============================================================

def _build_flux_arguments(prompt: str, is_personal: bool, seed: Optional[int] = None) -> tuple:
    """בונה ארגומנטים לקריאה ל-Flux. מחזיר (endpoint, arguments)."""
    use_lora = is_personal and SHALHEVET_LORA_URL

    # אם פאנל אישי + יש לורה — לוודא ש-trigger word בתחילת הפרומפט
    if use_lora and SHALHEVET_LORA_TRIGGER not in prompt[:60].lower():
        prompt = f"{SHALHEVET_LORA_TRIGGER}, {prompt}"

    base_args = {
        "prompt": prompt,
        "image_size": FLUX_IMAGE_SIZE,
        "num_inference_steps": FLUX_INFERENCE_STEPS,
        "enable_safety_checker": False,
    }
    if seed is not None:
        base_args["seed"] = seed

    if use_lora:
        endpoint = FLUX_LORA_ENDPOINT
        base_args["loras"] = [{"path": SHALHEVET_LORA_URL, "scale": 1.0}]
    else:
        endpoint = FLUX_ENDPOINT

    return endpoint, base_args


def generate_panel_image(panel: Dict, output_dir: Path,
                          prompt_override: Optional[str] = None,
                          filename_override: Optional[str] = None) -> Optional[Path]:
    """
    מייצר תמונה אחת לפאנל באמצעות Flux.

    Args:
        panel: dict הפאנל (מ-parse_panels_from_storyboard)
        output_dir: לאן לשמור
        prompt_override: אופציונלי — פרומפט שונה מהמקורי (ל-candidate generation)
        filename_override: אופציונלי — שם קובץ שונה מ-panel_X.png
    """
    panel_num = panel['number']
    personal_marker = " 🪞" if panel.get('is_personal') else ""

    # שלב 1: קבלת פרומפט
    if prompt_override:
        prompt = prompt_override
    else:
        extracted = extract_ready_prompts_from_panel(panel['content'])
        if 'image_prompt' in extracted:
            prompt = extracted['image_prompt']
        else:
            print(f"      🧠 מרחיב פרומפט עם הסקיל...")
            result = expand_panel_to_image_prompt(panel['content'])
            prompt = result['prompt']

    if panel['is_typography']:
        return None  # caller should not pass typography panels

    # שלב 2: בניית ארגומנטים והפעלת Flux
    endpoint, arguments = _build_flux_arguments(prompt, panel.get('is_personal', False))

    try:
        handler = fal_client.submit(endpoint, arguments=arguments)
        result = handler.get()
    except Exception as e:
        print(f"      ❌ פאנל {panel_num} שגיאת fal.ai: {e}")
        return None

    # שלב 3: חילוץ URL והורדה
    images = result.get("images", []) if isinstance(result, dict) else []
    if not images:
        print(f"      ❌ פאנל {panel_num} Flux לא החזיר תמונות: {str(result)[:150]}")
        return None

    image_url = images[0].get("url") if isinstance(images[0], dict) else None
    if not image_url:
        print(f"      ❌ פאנל {panel_num} אין URL בתשובה")
        return None

    filename = filename_override or f"panel_{panel_num}.png"
    image_path = output_dir / filename
    try:
        response = requests.get(image_url, timeout=60)
        response.raise_for_status()
        with open(image_path, 'wb') as f:
            f.write(response.content)
    except Exception as e:
        print(f"      ❌ פאנל {panel_num} הורדה נכשלה: {e}")
        return None

    print(f"      ✅ {filename} ({len(response.content):,} bytes){personal_marker}")
    return image_path


# ============================================================
# Phase 2: Multi-angle candidate generation
# ============================================================

def generate_three_angle_prompts(panel: Dict) -> List[str]:
    """
    מקבל פאנל ומייצר 3 פרומפטי תמונה שונים זוויתית — לא וריאציות seed.

    האסטרטגיה:
    - candidate 1: הפרומפט המקורי מהסטוריבורד
    - candidate 2: זווית/דגש שונה משמעותית (Claude)
    - candidate 3: זווית/דגש שונה אחר (Claude)

    כל 3 חולקים אותה כוונת תסריט וטון רגשי, אבל מציעים 3 דרכי קומפוזיציה שונות.
    """
    panel_num = panel['number']

    # קבל את הפרומפט המקורי
    extracted = extract_ready_prompts_from_panel(panel['content'])
    if 'image_prompt' in extracted:
        original = extracted['image_prompt']
    else:
        result = expand_panel_to_image_prompt(panel['content'])
        original = result['prompt']

    # בקש 2 חלופות מ-Claude
    skill_brain = load_skill_content()

    system = f"""You are the b-roll-prompter creative brain, generating ALTERNATIVE
camera angle interpretations for a single reel panel.

The user already has ONE interpretation (the original). Your job is to provide
2 ALTERNATIVE angles that convey the SAME script line and emotional intent,
but use MEANINGFULLY DIFFERENT camera positions and compositions — not seed
variations of the same idea.

==== THE CREATIVE BRAIN (b-roll-prompter skill) ====

{skill_brain}

==== END OF CREATIVE BRAIN ====

==== YOUR TASK — DIFFERENTIATION RULES ====

For each alternative, you must:

1. Apply Camera-First geometric specifications (where the camera is, what's
   visible, what's NOT visible, depth of field).
2. Honor the same genre, palette, and mood as the original.
3. Create a TRULY DIFFERENT framing — different shot scale or different vantage.
   - Different shot scales: extreme close-up, close-up, medium, wide, extreme wide
   - Different vantage points: behind the subject, from the side, from above,
     from below, front, three-quarter
4. Each alternative should reveal a different facet of the moment.

Examples of MEANINGFUL alternatives (not just variations):

ORIGINAL: "POV from inside an empty oven looking outward at the woman opening the door"
ALT-A: "Close-up on the woman's face from outside as she opens the oven, her
        eyes registering the emptiness, oven interior reflected in her pupils"
ALT-B: "Wide shot from behind the woman, showing her small silhouette against
        the open glowing oven cavity, full kitchen visible around her"

(Note how all three convey "she opens an empty oven" but from radically different angles.)

==== ANTI-PATTERNS — DO NOT GENERATE ====

- Same vantage with slight prop changes ("camera 30cm above" vs "35cm above")
- Same shot scale, just different lighting
- Variations of the same composition with different elements

==== OUTPUT FORMAT ====

Return ONLY valid JSON, no preamble:

{{
  "alt_a": {{
    "angle_summary": "one short Hebrew sentence describing this angle's distinct contribution",
    "prompt": "the full English image prompt, 250-400 words, Camera-First, ready to paste"
  }},
  "alt_b": {{
    "angle_summary": "one short Hebrew sentence describing this angle's distinct contribution",
    "prompt": "the full English image prompt, 250-400 words, Camera-First, ready to paste"
  }}
}}"""

    user = f"""==== PANEL CONTEXT ====

{panel['content']}

==== ORIGINAL INTERPRETATION (ANGLE 1) ====

{original}

==== YOUR TASK ====

Generate 2 alternative camera angles (ALT-A and ALT-B) that interpret the same
panel from radically different vantage points. Return the JSON object only."""

    response = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```\s*$', '', raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            raise RuntimeError(f"Claude לא החזיר JSON תקין לפאנל {panel_num}: {raw[:300]}")
        data = json.loads(match.group(0))

    alt_a = data.get('alt_a', {}).get('prompt', '').strip()
    alt_b = data.get('alt_b', {}).get('prompt', '').strip()

    if not alt_a or not alt_b:
        raise RuntimeError(f"Claude לא החזיר 2 חלופות שלמות לפאנל {panel_num}")

    return [original, alt_a, alt_b]


def generate_panel_candidates(panel: Dict, output_dir: Path) -> List[Path]:
    """
    מייצר 3 candidate images לפאנל — 3 זוויות שונות.

    Returns:
        רשימת 3 Path objects: panel_X_candidate_1.png .. _3.png
    """
    panel_num = panel['number']
    personal_marker = " 🪞 (אישי)" if panel.get('is_personal') else ""
    print(f"   🎨 פאנל {panel_num}{personal_marker} — מייצר 3 candidates...")

    if panel['is_typography']:
        print(f"      ⏩ פאנל טיפוגרפי — מדלג")
        return []

    # שלב 1: יצירת 3 פרומפטים שונים זוויתית
    try:
        prompts = generate_three_angle_prompts(panel)
    except Exception as e:
        print(f"      ❌ שגיאה ביצירת פרומפטים: {e}")
        return []

    print(f"      📝 קיבלתי 3 זוויות שונות, מייצר תמונות...")

    # שלב 2: יצירת תמונה לכל פרומפט במקבילי
    candidate_paths: List[Optional[Path]] = [None, None, None]

    def _generate_one(idx: int, prompt: str) -> Optional[Path]:
        return generate_panel_image(
            panel,
            output_dir,
            prompt_override=prompt,
            filename_override=f"panel_{panel_num}_candidate_{idx + 1}.png"
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_generate_one, i, p): i
            for i, p in enumerate(prompts)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
                if result:
                    candidate_paths[idx] = result
            except Exception as e:
                print(f"      ❌ candidate {idx + 1} נכשל: {e}")

    successful = [p for p in candidate_paths if p is not None]
    print(f"      📊 פאנל {panel_num}: {len(successful)}/3 candidates")
    return successful


def estimate_cost(num_panels: int) -> str:
    """אומדן עלות לפי Flux Pro v1.1 ב-fal.ai (~$0.04-0.05 לתמונה)."""
    cost_per_image = 0.05
    total = num_panels * cost_per_image
    return f"~${total:.2f} ({num_panels} × ~${cost_per_image:.2f})"


def generate_all_images(storyboard: str, output_dir: Path) -> List[Path]:
    """
    מייצר תמונה אחת לכל פאנל סצנה (לא טיפוגרפי).

    Note (Phase 1): כרגע 1 תמונה לפאנל. ב-Phase 2 ייווסף מנגנון 3 candidates + judge.
    """
    if not os.environ.get("FAL_KEY"):
        print("   ❌ חסר FAL_KEY ב-.env — אי אפשר להריץ Flux")
        return []

    # ניתוח
    panels = parse_panels_from_storyboard(storyboard)
    relevant = [p for p in panels if not p['is_typography']]
    personal_count = sum(1 for p in relevant if p['is_personal'])

    print(f"\n   📋 זוהו {len(panels)} פאנלים, {len(relevant)} מתאימים לתמונות")
    if personal_count:
        print(f"   🪞 {personal_count} פאנלים אישיים (ישתמשו ב-LoRA: {SHALHEVET_LORA_TRIGGER})")
        if not SHALHEVET_LORA_URL:
            print(f"   ⚠️  אין SHALHEVET_LORA_URL ב-.env — פאנלים אישיים יוצרו ללא LoRA")

    print(f"\n   🎨 Flux endpoint: {FLUX_ENDPOINT}")
    print(f"   📐 Image size: {FLUX_IMAGE_SIZE}")
    print(f"   ⚡ {FLUX_PARALLEL} משימות במקבילי")
    print(f"   💰 עלות מוערכת: {estimate_cost(len(relevant))}")
    print()

    # יצירה במקבילי
    image_paths = []
    with ThreadPoolExecutor(max_workers=FLUX_PARALLEL) as executor:
        futures = {
            executor.submit(generate_panel_image, panel, output_dir): panel['number']
            for panel in relevant
        }
        for future in as_completed(futures):
            panel_num = futures[future]
            try:
                result = future.result()
                if result:
                    image_paths.append(result)
            except Exception as e:
                print(f"   ❌ פאנל {panel_num} נכשל: {e}")

    print(f"\n   📊 סיכום: {len(image_paths)}/{len(relevant)} תמונות נוצרו בהצלחה")
    return image_paths


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            sb = f.read()
        out_dir = Path(sys.argv[2])
        out_dir.mkdir(parents=True, exist_ok=True)
        result = generate_all_images(sb, out_dir)
        print(f"\nנוצרו {len(result)} תמונות")
    else:
        print("Usage: python generate_images.py <storyboard_path> <output_dir>")
