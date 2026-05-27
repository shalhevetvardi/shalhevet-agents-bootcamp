#!/usr/bin/env python3
"""
סוקר את כל ההקלטות הקיימות בתיקיית Zoom ומסמן אותן כ-processed.
מריצים פעם אחת כדי שהפייפליין יתעלם מהקלטות ישנות ויעבד רק חדשות.

שימוש:
  python3 init_processed.py          # dry-run — מציג מה יסומן
  python3 init_processed.py --save   # שומר לקובץ processed_files.json
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

def _normalize_path(path: str) -> str:
    """מנרמל נתיב — מחליף את תיקיית הבית ב-~ כדי שיעבוד בכל מחשב."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


# טעינת config
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, "config.json"), "r", encoding="utf-8") as f:
    config = json.load(f)

zoom_path = os.path.expanduser(config["zoom_recordings_path"])
processed_path = os.path.join(script_dir, config.get("processed_files_path", "processed_files.json"))

# טעינת processed קיים (אם יש)
if os.path.exists(processed_path):
    with open(processed_path, "r", encoding="utf-8") as f:
        processed = json.load(f)
    print(f"📂 נטען processed_files.json קיים עם {len(processed)} רשומות")
else:
    processed = {}
    print("📂 אין processed_files.json — יוצר חדש")

# סריקת כל ההקלטות
skip_dirs = {'zoom-workflow', 'פרומפטים לחילוץ מתמלולים', '.', '..'}
count = 0
new_count = 0

for subfolder in sorted(Path(zoom_path).iterdir()):
    if not subfolder.is_dir():
        continue
    if subfolder.name.startswith('.') or subfolder.name in skip_dirs:
        continue

    # חיפוש קבצי אודיו
    audio_files = list(subfolder.glob("*.m4a")) + list(subfolder.glob("*.mp3"))
    if not audio_files:
        # fallback ל-mp4
        audio_files = list(subfolder.glob("*.mp4"))
    if not audio_files:
        continue

    for audio_file in audio_files:
        file_key = str(audio_file)
        count += 1

        if file_key not in processed:
            processed[file_key] = {
                "status": "pre_existing",
                "timestamp": datetime.now().isoformat(),
                "note": "סומן כ-processed באתחול ראשוני"
            }
            new_count += 1

print(f"\n📊 סה\"כ קבצי אודיו: {count}")
print(f"🆕 חדשים שיסומנו: {new_count}")
print(f"📁 כבר ב-processed: {count - new_count}")

if "--save" in sys.argv:
    with open(processed_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"\n✅ נשמר: {processed_path} ({len(processed)} רשומות)")
else:
    print(f"\n⚠️  DRY RUN — לא נשמר. הוסיפי --save כדי לשמור.")
