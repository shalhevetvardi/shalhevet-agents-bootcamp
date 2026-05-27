"""
יצירת טיוטת Gmail דרך Gmail API — עם refresh_token (ללא OAuth אינטראקטיבי).
משתמש ב-client_id + client_secret + refresh_token מ-.env.
"""
import base64
import logging
import os
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from modules.render_email import render_email, PODCAST_EPISODES, _should_add_podcast

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailDraftCreator:
    """
    יוצר טיוטות ב-Gmail ללא OAuth אינטראקטיבי.
    משתמש ב-refresh_token (מוצא אוטומטית access_token חדש בכל פעם שצריך).
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, composer):
        self.composer = composer
        self.from_address = os.environ.get("GMAIL_FROM_ADDRESS", "me")
        self.creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        # לרענון access token ראשוני
        self.creds.refresh(Request())
        self.gmail_service = build("gmail", "v1", credentials=self.creds, cache_discovery=False)

    def create_draft(
        self,
        to_email: str,
        lead_name: str,
        insights: Dict[str, Any],
        templates_dir: Path,
        logo_path: Optional[Path] = None,
        pdf_path: Optional[Path] = None,
        transcript: str = "",
    ) -> Dict[str, Any]:
        """
        יוצר טיוטה ב-Gmail. מחזיר: id, message_id, link, subject

        מבנה ה-MIME:
        mixed
         └── related
         │    ├── alternative
         │    │    ├── text/plain
         │    │    └── text/html
         │    └── image/png (inline, CID)
         └── application/pdf (attachment, אם יש)

        העטיפה ב-multipart/related חיונית — בלעדיה קישור ה-CID של הלוגו
        נשבר ברוב הלקוחות אחרי שליחה בפועל (הטיוטה עצמה ב-Gmail פחות קפדנית).
        """
        composed = self.composer.compose(
            lead_name=lead_name,
            insights=insights,
            transcript=transcript,
        )

        rendered = render_email(
            lead_full_name=lead_name,
            insights=insights,
            composed=composed,
            templates_dir=templates_dir,
            logo_path=logo_path,
        )

        first_name = lead_name.split()[0] if lead_name else ""
        if _should_add_podcast(insights):
            lines = ["🎧 בנוסף, הבטחתי לך כמה פרקים מהפודקאסט שלי:"]
            for title, url in PODCAST_EPISODES:
                lines.append(f"  • {title} — {url}")
            promise_section = "\n".join(lines) + "\n\n"
        else:
            promise_section = f"{composed['promise_line']}\n\n" if composed.get('promise_line', '').strip() else ""
        plain = (
            f"היי {first_name},\n\n"
            f"{composed['personal_opening']}\n\n"
            f"{promise_section}"
            f"— שלהבת, אִימפּרוּב"
        )

        msg = MIMEMultipart("mixed")
        msg["To"] = to_email
        msg["From"] = self.from_address
        msg["Subject"] = rendered["subject"]

        # alternative: plain + html
        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(plain, "plain", "utf-8"))
        alt.attach(MIMEText(rendered["html"], "html", "utf-8"))

        # related: עוטף את ה-alternative + התמונה inline, כדי ש-cid:<logo>
        # ייפתר ע"י הלקוח אצל הנמען גם אחרי שליחה.
        if rendered["logo_bytes"]:
            related = MIMEMultipart("related")
            related.attach(alt)
            img = MIMEImage(rendered["logo_bytes"], _subtype="png")
            img.add_header("Content-ID", f"<{rendered['logo_cid']}>")
            img.add_header("Content-Disposition", "inline", filename="logo.png")
            related.attach(img)
            msg.attach(related)
        else:
            msg.attach(alt)

        if rendered["track"] in (1, 2) and pdf_path and pdf_path.exists():
            pdf_bytes = pdf_path.read_bytes()
            pdf = MIMEApplication(pdf_bytes, _subtype="pdf")
            pdf.add_header(
                "Content-Disposition",
                "attachment",
                filename="טירונות-סוכנים.pdf",
            )
            msg.attach(pdf)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        draft = self.gmail_service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        draft_id = draft["id"]
        message_id = draft["message"]["id"]
        link = f"https://mail.google.com/mail/u/0/#drafts?compose={message_id}"
        log.info("Created draft %s for %s, track=%d", draft_id, to_email, rendered["track"])

        return {
            "id": draft_id,
            "message_id": message_id,
            "link": link,
            "subject": rendered["subject"],
        }
