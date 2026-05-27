"""
ניתוח תמלול שיחה דרך Claude.

ClaudeAnalyzer.analyze() → dict מובנה (סכמה מה-prompt) + מחרוזת JSON pretty printed.
EmailComposer.compose() → dict עם חמישה שדות דינמיים
(subject, personal_opening, personal_paragraph_with_quote,
personal_paragraph_without_quote, promise_line).
"""
import os
import re
import json
import logging
from typing import Any, Dict, Tuple
from anthropic import Anthropic

log = logging.getLogger(__name__)


def _extract_json(text: str) -> Dict[str, Any]:
    """
    מחלץ JSON חוקי ממחרוזת שהגיעה מ-LLM.
    תומך ב:
    - JSON גולמי (ללא fence)
    - JSON עטוף ב-```json ... ```
    - JSON עם טקסט לפני/אחרי (לוקח את הבלוק הראשון של {...})
    """
    if not text:
        raise ValueError("empty LLM response")

    # 1) אם יש markdown fence — מסיר
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))

    # 2) ניסיון ישיר — אולי הפלט כולו JSON תקין
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 3) חיפוש הבלוק הראשון של {...} (balanced braces)
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in response: {text[:200]}")

    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                return json.loads(candidate)

    raise ValueError(f"unbalanced JSON in response: {text[:200]}")


class ClaudeAnalyzer:
    def __init__(self, api_key: str, model: str, prompts_dir: str, max_tokens: int = 2000):
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        with open(os.path.join(prompts_dir, "analysis.txt"), encoding="utf-8") as f:
            self.system_prompt = f.read()

    def analyze(self, transcript: str, lead_name: str = "") -> Tuple[Dict[str, Any], str]:
        """
        מחזיר טאפל: (insights_dict, insights_json_pretty)
        - insights_dict — מילון Python מובנה לפי הסכמה ב-analysis.txt
        - insights_json_pretty — JSON pretty-printed לכתיבה ל-Airtable (שדה ai_insights)
        """
        user_msg = (
            f"שם הליד: {lead_name or 'לא ידוע'}\n\n"
            f"תמלול השיחה:\n---\n{transcript}\n---\n\n"
            "נתחי את השיחה לפי ההנחיות במערכת. החזירי JSON אחד בלבד."
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        try:
            insights = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.error("Failed to parse analyst JSON: %s\nRaw: %s", e, raw[:500])
            raise
        pretty = json.dumps(insights, ensure_ascii=False, indent=2)
        return insights, pretty


class EmailComposer:
    """מחבר את 5 השדות הדינמיים של המייל בעזרת Claude."""
    def __init__(self, api_key: str, model: str, prompts_dir: str, max_tokens: int = 2500):
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        with open(os.path.join(prompts_dir, "email_draft_v2.txt"), encoding="utf-8") as f:
            self.system_prompt = f.read()

    def compose(self, lead_name: str, insights: Dict[str, Any], transcript: str = "") -> Dict[str, str]:
        """
        מקבל את dict התובנות (מה-analyst) + שם ליד + תמלול השיחה.
        מחזיר dict עם 5 שדות:
        subject, personal_opening, personal_paragraph_with_quote,
        personal_paragraph_without_quote, promise_line.
        """
        insights_json = json.dumps(insights, ensure_ascii=False, indent=2)
        user_msg = (
            f"lead_name: {lead_name or 'ללא שם'}\n\n"
            f"transcript:\n---\n{transcript or '(לא סופק תמלול)'}\n---\n\n"
            f"JSON מהאנליסט:\n{insights_json}\n\n"
            "החזירי JSON אחד עם 5 השדות: subject, personal_opening, "
            "personal_paragraph_with_quote, personal_paragraph_without_quote, promise_line."
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        try:
            composed = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.error("Failed to parse composer JSON: %s\nRaw: %s", e, raw[:500])
            raise

        # ולידציה של מפתחות
        required_keys = (
            "subject",
            "personal_opening",
            "personal_paragraph_with_quote",
            "personal_paragraph_without_quote",
            "promise_line",
        )
        for key in required_keys:
            if key not in composed:
                log.warning("Composer output missing key '%s' — defaulting to empty", key)
                composed[key] = ""

        return {
            "subject": str(composed["subject"]).strip(),
            "personal_opening": str(composed["personal_opening"]).strip(),
            "personal_paragraph_with_quote": str(composed["personal_paragraph_with_quote"]).strip(),
            "personal_paragraph_without_quote": str(composed["personal_paragraph_without_quote"]).strip(),
            "promise_line": str(composed["promise_line"]).strip(),
        }
