#!/usr/bin/env python3
"""
zoom_watcher.py — מזהה הקלטות זום חדשות ומריץ את הפייפליין אוטומטית.

משתמש ב-fsevents (macOS) דרך watchdog לזהות קבצי m4a/mp3 חדשים
בתיקיית Zoom. כשנמצא קובץ אודיו חדש שלא ב-processed_files.json,
ממתין שהקובץ יסיים להיכתב ואז מריץ את zoom_pipeline.py.

שימוש:
  python3 zoom_watcher.py              # רץ ברקע, עוצר עם Ctrl+C
  python3 zoom_watcher.py --once       # סורק פעם אחת ויוצא (כמו cron)

דרישות:
  pip install watchdog
"""

import os
import sys
import json
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# ─── הגדרות ──────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
PIPELINE_SCRIPT = os.path.join(SCRIPT_DIR, "zoom_pipeline.py")
WATCHER_LOG = os.path.join(SCRIPT_DIR, "watcher.log")

# זמן המתנה (שניות) אחרי זיהוי קובץ חדש — כדי לוודא שזום סיים לכתוב
SETTLE_TIME = 300  # 2 דקות

# קבצי אודיו שמעניינים אותנו
AUDIO_EXTENSIONS = {'.m4a', '.mp3'}

# תיקיות שמדלגים עליהן
SKIP_DIRS = {'zoom-workflow', 'פרומפטים לחילוץ מתמלולים'}

def _normalize_path(path: str) -> str:
    """מנרמל נתיב — מחליף את תיקיית הבית ב-~."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


# ─── Setup ───────────────────────────────────────────────────────

def setup_logging():
    logger = logging.getLogger("zoom_watcher")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # קובץ
    fh = logging.FileHandler(WATCHER_LOG, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # מסך
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_processed():
    config = load_config()
    path = os.path.join(SCRIPT_DIR, config.get("processed_files_path", "processed_files.json"))
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def find_new_recordings(logger):
    """סורק את תיקיית Zoom ומחזיר הקלטות חדשות (לא ב-processed)."""
    config = load_config()
    zoom_path = os.path.expanduser(config["zoom_recordings_path"])
    processed = load_processed()

    new_recordings = []

    for subfolder in sorted(Path(zoom_path).iterdir()):
        if not subfolder.is_dir():
            continue
        if subfolder.name.startswith('.') or subfolder.name in SKIP_DIRS:
            continue

        audio_files = []
        for ext in AUDIO_EXTENSIONS:
            audio_files.extend(subfolder.glob(f"*{ext}"))

        for audio_file in audio_files:
            file_key = str(audio_file)
            if file_key not in processed:
                new_recordings.append({
                    "folder_name": subfolder.name,
                    "audio_path": file_key,
                    "size_mb": round(audio_file.stat().st_size / (1024 * 1024), 1),
                })

    return new_recordings


def wait_for_file_stable(file_path, logger, check_interval=30, stable_count=2):
    """ממתין שקובץ יפסיק לגדול (סימן שזום סיים לכתוב)."""
    prev_size = -1
    stable_checks = 0

    while stable_checks < stable_count:
        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            logger.warning(f"קובץ לא נגיש: {file_path}")
            time.sleep(check_interval)
            continue

        if current_size == prev_size and current_size > 0:
            stable_checks += 1
            logger.debug(f"קובץ יציב ({stable_checks}/{stable_count}): {file_path}")
        else:
            stable_checks = 0
            logger.debug(f"קובץ עדיין גדל: {current_size / (1024*1024):.1f} MB")

        prev_size = current_size
        time.sleep(check_interval)

    logger.info(f"✅ קובץ יציב: {os.path.basename(file_path)} ({current_size / (1024*1024):.1f} MB)")


def run_pipeline(logger):
    """מריץ את zoom_pipeline.py כתהליך נפרד."""
    logger.info("🚀 מריץ את הפייפליין...")

    try:
        result = subprocess.run(
            [sys.executable, PIPELINE_SCRIPT],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 שעות מקסימום
        )

        if result.returncode == 0:
            logger.info("✅ הפייפליין סיים בהצלחה")
            # הצגת שורות סיכום
            for line in result.stdout.split("\n"):
                if "הצלחות" in line or "שגיאות" in line or "נשמר ב-Notion" in line:
                    logger.info(f"   {line.strip()}")
        else:
            logger.error(f"❌ הפייפליין נכשל (exit code {result.returncode})")
            logger.error(f"   stderr: {result.stderr[:500]}")

    except subprocess.TimeoutExpired:
        logger.error("❌ הפייפליין חרג מזמן המקסימום (2 שעות)")
    except Exception as e:
        logger.error(f"❌ שגיאה בהרצת הפייפליין: {e}")


# ─── מצב --once (סריקה חד-פעמית) ────────────────────────────────

def run_once(logger):
    """סורק פעם אחת, מעבד הקלטות חדשות, ויוצא."""
    logger.info("🔍 סריקה חד-פעמית...")

    new_recordings = find_new_recordings(logger)

    if not new_recordings:
        logger.info("אין הקלטות חדשות.")
        return

    logger.info(f"🆕 נמצאו {len(new_recordings)} הקלטות חדשות:")
    for rec in new_recordings:
        logger.info(f"   📂 {rec['folder_name']} ({rec['size_mb']} MB)")

    # המתנה שהקבצים יהיו יציבים
    for rec in new_recordings:
        wait_for_file_stable(rec["audio_path"], logger)

    # הרצת הפייפליין
    run_pipeline(logger)


# ─── מצב watcher (רציף) ─────────────────────────────────────────

def run_watcher(logger):
    """רץ ברציפות ומזהה הקלטות חדשות."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        logger.error("❌ חסר watchdog! התקיני: pip install watchdog")
        logger.info("💡 אלטרנטיבה: הריצי עם --once כ-cron job")
        sys.exit(1)

    config = load_config()
    zoom_path = os.path.expanduser(config["zoom_recordings_path"])

    class ZoomHandler(FileSystemEventHandler):
        def __init__(self):
            self.pending = {}  # file_path → timestamp שזוהה

        def on_created(self, event):
            if event.is_directory:
                return

            path = Path(event.src_path)
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                return

            # דילוג על תיקיות מיוחדות
            if any(skip in str(path) for skip in SKIP_DIRS):
                return

            logger.info(f"🆕 זוהה קובץ חדש: {path.name}")
            self.pending[str(path)] = time.time()

        def check_pending(self):
            """בודק אם יש קבצים שחיכו מספיק זמן."""
            now = time.time()
            ready = []

            for path, detected_time in list(self.pending.items()):
                if now - detected_time >= SETTLE_TIME:
                    # בודק שהקובץ לא ב-processed
                    processed = load_processed()
                    if path not in processed:
                        ready.append(path)
                    del self.pending[path]

            return ready

    handler = ZoomHandler()
    observer = Observer()
    observer.schedule(handler, zoom_path, recursive=True)
    observer.start()

    logger.info(f"👀 מאזין לתיקייה: {zoom_path}")
    logger.info("   לעצירה: Ctrl+C")

    # גם בודק הקלטות שכבר נוחתו (אבל לא עובדו)
    initial_new = find_new_recordings(logger)
    if initial_new:
        logger.info(f"🆕 נמצאו {len(initial_new)} הקלטות חדשות שלא עובדו:")
        for rec in initial_new:
            logger.info(f"   📂 {rec['folder_name']}")
        run_pipeline(logger)

    try:
        while True:
            time.sleep(30)
            ready = handler.check_pending()
            if ready:
                logger.info(f"⏰ {len(ready)} הקלטות מוכנות לעיבוד")
                run_pipeline(logger)
    except KeyboardInterrupt:
        logger.info("👋 עוצר...")
        observer.stop()

    observer.join()
    logger.info("סיום.")


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger = setup_logging()
    logger.info("=" * 50)
    logger.info("Zoom Watcher — מתחיל")
    logger.info("=" * 50)

    if "--once" in sys.argv:
        run_once(logger)
    else:
        run_watcher(logger)
