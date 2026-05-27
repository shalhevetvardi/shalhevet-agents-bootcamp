"""
מרכיב HTML סופי למייל מתוך template + בלוקים.

הפונקציה המרכזית: `render_email(first_name, insights, composed, templates_dir, logo_path)`.

- בוחרת template לפי insights["track"]
- מזריקה blocks פרסונה + value לפי persona_id + gender (track 1 בלבד)
- ממלאת 9 placeholders:
  {logo_img}, {first_name}, {personal_opening},
  {personal_paragraph_with_quote}, {personal_paragraph_without_quote},
  {promise_line}, {persona_message_block}, {value_block_gendered}, {ps_verb_gendered}
- הלוגו משובץ כ-CID (cid:logo) — render_email מחזירה גם את קובץ הלוגו כ-bytes כדי
  שה-email_drafter יוכל לצרף אותו inline.
"""
import base64
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)

# מיפוי track → שם קובץ template
TRACK_TEMPLATES = {
    1: "track_1_accepted.html",
    2: "track_2_beginners.html",
    3: "track_3_referral.html",
}

# פועל PS לפי מגדר
PS_VERBS = {
    "female": "תבני",
    "male": "תבנה",
    None: "תבני/תבנה",
}

LOGO_CID = "aimprove_logo"
PUBLIC_LOGO_URL = "https://shalhevetvardi.github.io/aimprove-assets/images/20260421_134445_חתול-טירונות-לבן.png"

PODCAST_EPISODES = [
    ("ככה בונים עסק שלם עם AI (בלי לשלם משכורות לעובדים)",
     "https://open.spotify.com/episode/5W3k6WkyIDbok1nvcsE1kh?si=RTCJs_abSs6Gd4GMz8pimQ"),
    ("כל האמת על סוכני AI לעסק",
     "https://open.spotify.com/episode/0iB07ory456ebG4TOHi3xw?si=X6oD__7GRCOzCyKRaoEGDQ"),
    ("ככה סוכן AI אמיתי נראה מבפנים",
     "https://open.spotify.com/episode/4kz6JAGdx2rWc9UnbbIsNB?si=mnt271SgTPuZ7bAT5mpAgA"),
    ("למה אני לא ממליצה להשתמש בקלוד קוד",
     "https://open.spotify.com/episode/3uS4wWnnvlBi4EDM5B2njs?si=x3EiuKbDReOqKYBny_pf4w"),
]


def _should_add_podcast(insights: Dict[str, Any]) -> bool:
    """בודק אם שלהבת הבטיחה פודקאסט בשיחה."""
    promise = insights.get("promise_in_call", {})
    if not promise or not promise.get("made"):
        return False
    content = (promise.get("content") or "").lower()
    return any(kw in content for kw in ("פודקאסט", "podcast", "פרק", "האזנה", "ספוטיפיי"))


def _build_podcast_block() -> str:
    """בונה HTML של קישורי פודקאסט בסגנון המייל — מחליף את promise_line."""
    links_html = ""
    for title, url in PODCAST_EPISODES:
        links_html += (
            f'<li style="margin-bottom:8px; color:#7c3aed; font-weight:700;">'
            f'<a href="{url}" style="color:#7c3aed; text-decoration:none; font-weight:700;">{title}</a>'
            f'</li>\n'
        )
    return (
        '<div style="direction:rtl; text-align:right; margin-top:20px;">\n'
        '<p style="margin:0 0 12px 0; font-weight:700; font-size:16px; text-align:center;">'
        '🎧 בנוסף, הבטחתי לך כמה פרקים מהפודקאסט שלי:</p>\n'
        f'<ul style="padding-right:18px; margin:0; list-style-type:disc;">\n{links_html}</ul>\n'
        '</div>'
    )


def _first_name(full_name: str) -> str:
    """מוציא את השם הפרטי בלבד."""
    if not full_name:
        return ""
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def _load_block(blocks_dir: Path, filename: str) -> str:
    path = blocks_dir / filename
    if not path.exists():
        log.warning("Block file missing: %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


def _build_logo_tag(logo_path: Optional[Path]) -> Tuple[str, Optional[bytes]]:
    """
    מחזיר (img_html, logo_bytes_for_attachment).
    - אם logo_path קיים — מחזיר <img src="cid:..."> + bytes לצירוף
    - אחרת — מחזיר placeholder ריק + None
    """
    # Use public GitHub Pages image and force centered compact logo in header.
    img_tag = (
        f'<img src="{PUBLIC_LOGO_URL}" alt="aimprove" '
        f'style="display:block; width:96px; max-width:96px; height:auto; margin:0 auto 16px auto;">'
    )
    return img_tag, None


def render_email(
    lead_full_name: str,
    insights: Dict[str, Any],
    composed: Dict[str, str],
    templates_dir: Path,
    logo_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    מרכיב את ה-HTML הסופי של המייל.

    מחזיר dict:
    {
      "subject": str,
      "html": str,
      "logo_bytes": Optional[bytes],  # לצירוף inline כ-CID
      "logo_cid": str,                 # המזהה של ה-CID
      "track": int,
    }
    """
    track = int(insights.get("track", 1) or 1)
    gender = insights.get("gender")  # "female" | "male" | None
    persona_id = insights.get("persona_id")

    # 1) בחירת template
    template_filename = TRACK_TEMPLATES.get(track, TRACK_TEMPLATES[1])
    template_path = templates_dir / template_filename
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    template_html = template_path.read_text(encoding="utf-8")

    # 2) first name
    first_name = _first_name(lead_full_name)

    # 3) logo
    logo_html, logo_bytes = _build_logo_tag(logo_path)

    # 4) PS verb
    ps_verb = PS_VERBS.get(gender, PS_VERBS[None])

    # 5) בלוק ערך (רק ל-track 1)
    blocks_dir = templates_dir / "blocks"
    value_block_html = ""

    if track == 1:
        # gender fallback — אם אין מגדר, לא להיתקע: נבחר female כברירת מחדל
        g = gender if gender in ("female", "male") else "female"
        value_block_html = _load_block(blocks_dir, f"value_block_{g}.html")

    # 6) החלפת placeholders
    html = template_html
    replacements = {
        "{logo_img}": logo_html,
        "{first_name}": first_name or "היי",
        "{personal_opening}": composed.get("personal_opening", "").strip(),
        "{personal_paragraph_with_quote}": composed.get("personal_paragraph_with_quote", "").strip(),
        "{personal_paragraph_without_quote}": composed.get("personal_paragraph_without_quote", "").strip(),
        "{promise_line}": composed.get("promise_line", "").strip(),
        "{value_block_gendered}": value_block_html,
        "{ps_verb_gendered}": ps_verb,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    if _should_add_podcast(insights):
        podcast_html = _build_podcast_block()
        promise_line_text = composed.get("promise_line", "").strip()
        if promise_line_text and promise_line_text in html:
            html = html.replace(promise_line_text, podcast_html)
        else:
            html = html.replace("</body>", podcast_html + "\n</body>")
        log.info("Podcast links block replaced promise_line in email")

    if track == 1:
        final_subject = f"{first_name}, התקבלת לטירונות סוכנים - כל הפרטים בפנים 🥳"
    else:
        final_subject = f"{first_name}, המסלול שמתאים לך ב-AI - כל הפרטים בפנים"

    return {
        "subject": final_subject,
        "html": html,
        "logo_bytes": logo_bytes,
        "logo_cid": LOGO_CID,
        "track": track,
    }
