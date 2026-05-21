#!/usr/bin/env python3
"""
סקריפט עריכת וידאו אוטומטית
==============================
פלואו:
  1. בחירת מצב: "סרטון מלא נקי" (רק הסרת שקטים) או "סרטון מצומצם" (בחירת נושאים + הסרת שקטים)
  2. אם מצומצם — בחירת נושאים (רחב / צר)
  3. חיתוך לפי נושאים (אם רלוונטי)
  4. הסרת שקטים אוטומטית
  5. קובץ סופי מוכן

שימוש:
  python3 edit_video.py <video_file>
  python3 edit_video.py <video_file> --topics topics.json
  python3 edit_video.py <video_file> --silence-only

דרישות: ffmpeg, ffprobe
"""

import subprocess
import json
import sys
import os
import re
import tempfile
import shutil
from pathlib import Path


# ============================================================
# הגדרות ברירת מחדל
# ============================================================
SILENCE_NOISE_DB = -28       # סף רעש לזיהוי שקט (dB) — -28 תופס יותר שקטים מ-30
SILENCE_MIN_DURATION = 0.8   # משך מינימלי של שקט לחיתוך (שניות) — 0.8 תופס הפסקות קצרות
PADDING = 0.15               # ריפוד קטן לפני ואחרי דיבור (שניות)


# ============================================================
# פונקציות עזר
# ============================================================
def ts_to_seconds(ts: str) -> float:
    """המרת timestamp בפורמט HH:MM:SS או MM:SS לשניות"""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def seconds_to_ts(s: float) -> str:
    """המרת שניות לפורמט HH:MM:SS.mmm"""
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def get_video_duration(video_path: str) -> float:
    """קבלת אורך הוידאו בשניות"""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def run_ffmpeg(args: list, desc: str = ""):
    """הרצת פקודת ffmpeg עם הודעת שגיאה"""
    if desc:
        print(f"  ⏳ {desc}...")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ❌ שגיאת FFmpeg: {result.stderr[:500]}")
        return False
    return True


# ============================================================
# שלב 1: בחירת נושאים (אם רלוונטי)
# ============================================================
def load_topics(topics_file: str) -> list:
    """טעינת נושאים מקובץ JSON"""
    with open(topics_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("topics", data) if isinstance(data, dict) else data


def interactive_topic_selection(topics: list) -> list:
    """בחירת נושאים אינטראקטיבית"""
    print("\n📋 נושאים בסרטון:")
    print("=" * 60)

    # בדיקה אם יש תתי-נושאים
    has_subtopics = any("subtopics" in t for t in topics)

    for i, topic in enumerate(topics):
        duration = ts_to_seconds(topic["end"]) - ts_to_seconds(topic["start"])
        mins = int(duration // 60)
        secs = int(duration % 60)
        print(f"  [{i+1}] {topic['name']}")
        print(f"      ⏱ {topic['start']} → {topic['end']} ({mins}:{secs:02d} דקות)")

        if has_subtopics and "subtopics" in topic:
            for j, sub in enumerate(topic["subtopics"]):
                sub_dur = ts_to_seconds(sub["end"]) - ts_to_seconds(sub["start"])
                print(f"      [{i+1}.{j+1}] {sub['name']} ({int(sub_dur//60)}:{int(sub_dur%60):02d})")

    print("=" * 60)

    # בחירת רמת דיוק
    if has_subtopics:
        print("\n🎯 באיזו רמה את רוצה לבחור?")
        print("  [1] רמה רחבה — נושאים ראשיים בלבד")
        print("  [2] רמה מפורטת — תתי-נושאים")
        level = input("\nבחרי (1/2): ").strip()
    else:
        level = "1"

    if level == "2":
        # בחירה ברמת תתי-נושאים
        print("\n✏️  הקלידי את המספרים של תתי-הנושאים שרוצה לשמור (מופרדים בפסיקים)")
        print("   לדוגמה: 1.1, 2.1, 2.3, 5.2")
        print("   או הקלידי 'all' לשמור הכל")

        choice = input("\nנושאים לשמור: ").strip()
        if choice.lower() == "all":
            return topics  # שמור הכל

        # פרסור הבחירה
        keep_pairs = []
        for item in choice.split(","):
            item = item.strip()
            if "." in item:
                parts = item.split(".")
                keep_pairs.append((int(parts[0]) - 1, int(parts[1]) - 1))

        # בניית רשימת קטעים לשמור
        segments = []
        for topic_idx, sub_idx in keep_pairs:
            if topic_idx < len(topics) and "subtopics" in topics[topic_idx]:
                subs = topics[topic_idx]["subtopics"]
                if sub_idx < len(subs):
                    segments.append({
                        "name": subs[sub_idx]["name"],
                        "start": subs[sub_idx]["start"],
                        "end": subs[sub_idx]["end"]
                    })
        return segments

    else:
        # בחירה ברמת נושאים ראשיים
        print("\n✏️  הקלידי את המספרים של הנושאים שרוצה לשמור (מופרדים בפסיקים)")
        print("   לדוגמה: 1,2,3,5")
        print("   או הקלידי 'all' לשמור הכל")

        choice = input("\nנושאים לשמור: ").strip()
        if choice.lower() == "all":
            return topics

        keep_ids = [int(x.strip()) - 1 for x in choice.split(",")]
        return [topics[i] for i in keep_ids if i < len(topics)]


def cut_by_topics(video_path: str, segments: list, work_dir: str) -> str:
    """חיתוך וידאו לפי נושאים נבחרים"""
    print(f"\n✂️  חיתוך לפי {len(segments)} נושאים נבחרים...")

    segment_files = []
    for i, seg in enumerate(segments):
        start = ts_to_seconds(seg["start"])
        end = ts_to_seconds(seg["end"])
        out_file = os.path.join(work_dir, f"topic_{i:03d}.mp4")

        success = run_ffmpeg([
            "-i", video_path,
            "-ss", str(start), "-to", str(end),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            out_file
        ], f"חותך: {seg['name']}")

        if success and os.path.exists(out_file):
            segment_files.append(out_file)

    if not segment_files:
        print("❌ לא נוצרו קטעים!")
        return video_path

    # חיבור הקטעים
    topics_output = os.path.join(work_dir, "topics_merged.mp4")
    concat_file = os.path.join(work_dir, "topics_concat.txt")

    with open(concat_file, "w") as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")

    success = run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", topics_output
    ], "מחבר קטעי נושאים")

    if success and os.path.exists(topics_output):
        return topics_output
    return video_path


# ============================================================
# שלב 2: הסרת שקטים
# ============================================================
def detect_silence(video_path: str) -> list:
    """זיהוי קטעי שקט בוידאו"""
    print(f"\n🔍 מזהה שקטים (סף: {SILENCE_NOISE_DB}dB, מינימום: {SILENCE_MIN_DURATION}s)...")

    result = subprocess.run(
        ["ffmpeg", "-i", video_path, "-af",
         f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_DURATION}",
         "-f", "null", "-"],
        capture_output=True, text=True
    )

    output = result.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", output)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", output)]

    silences = list(zip(starts[:len(ends)], ends))

    total_silence = sum(e - s for s, e in silences)
    duration = get_video_duration(video_path)
    pct = (total_silence / duration * 100) if duration > 0 else 0

    print(f"  📊 נמצאו {len(silences)} קטעי שקט")
    print(f"  📊 סה\"כ שקט: {total_silence:.1f}s ({pct:.1f}% מהסרטון)")

    return silences


def build_speech_segments(silences: list, duration: float) -> list:
    """בניית רשימת קטעי דיבור (ההיפוך של שקטים) — ללא חפיפות

    תיקון: הגרסה הקודמת השתמשה ב-PADDING שגרם לחפיפות בין קטעים
    כשהיו הרבה שקטים קצרים, מה שהפך את הפלט לארוך יותר מהמקור.
    הגרסה הזו עוקבת אחרי last_end ומונעת חפיפה.
    """
    segments = []
    current = 0.0
    last_end = 0.0

    for s_start, s_end in silences:
        speech_start = max(last_end, current)
        speech_end = s_start

        if speech_end - speech_start > 0.05:
            segments.append((speech_start, speech_end))
        current = s_end
        last_end = speech_end if speech_end > last_end else last_end

    # קטע אחרון
    if current < duration:
        segments.append((current, duration))

    return segments


def remove_silence(video_path: str, work_dir: str, output_path: str) -> bool:
    """הסרת שקטים מהוידאו"""
    silences = detect_silence(video_path)

    if not silences:
        print("  ✅ לא נמצאו שקטים — מעתיק את הקובץ כמו שהוא")
        shutil.copy2(video_path, output_path)
        return True

    duration = get_video_duration(video_path)
    speech_segments = build_speech_segments(silences, duration)

    print(f"\n✂️  חותך {len(speech_segments)} קטעי דיבור...")

    segment_files = []
    for i, (start, end) in enumerate(speech_segments):
        out_file = os.path.join(work_dir, f"speech_{i:04d}.mp4")

        success = run_ffmpeg([
            "-i", video_path,
            "-ss", str(start), "-to", str(end),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            out_file
        ])

        if success and os.path.exists(out_file):
            segment_files.append(out_file)

        # הדפסת התקדמות
        if (i + 1) % 20 == 0 or i == len(speech_segments) - 1:
            print(f"  📦 {i+1}/{len(speech_segments)} קטעים")

    # חיבור כל הקטעים
    print(f"\n🔗 מחבר {len(segment_files)} קטעי דיבור...")
    concat_file = os.path.join(work_dir, "speech_concat.txt")

    with open(concat_file, "w") as f:
        for sf in segment_files:
            f.write(f"file '{sf}'\n")

    return run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c", "copy", output_path
    ], "מייצר קובץ סופי")


# ============================================================
# פלואו ראשי
# ============================================================
def main():
    # בדיקת ארגומנטים
    if len(sys.argv) < 2:
        print("שימוש: python3 edit_video.py <video_file> [--silence-only] [--topics topics.json]")
        print("\nדוגמאות:")
        print("  python3 edit_video.py video.mp4                     # מצב אינטראקטיבי")
        print("  python3 edit_video.py video.mp4 --silence-only      # רק הסרת שקטים")
        print("  python3 edit_video.py video.mp4 --topics topics.json # נושאים מקובץ + הסרת שקטים")
        sys.exit(1)

    video_path = sys.argv[1]
    if not os.path.exists(video_path):
        print(f"❌ קובץ לא נמצא: {video_path}")
        sys.exit(1)

    silence_only = "--silence-only" in sys.argv
    topics_file = None
    if "--topics" in sys.argv:
        idx = sys.argv.index("--topics")
        if idx + 1 < len(sys.argv):
            topics_file = sys.argv[idx + 1]

    # מידע על הסרטון
    duration = get_video_duration(video_path)
    mins = int(duration // 60)
    secs = int(duration % 60)
    size_mb = os.path.getsize(video_path) / (1024 * 1024)

    print("=" * 60)
    print("🎬 עריכת וידאו אוטומטית")
    print("=" * 60)
    print(f"📁 קובץ: {os.path.basename(video_path)}")
    print(f"⏱  אורך: {mins}:{secs:02d} דקות")
    print(f"💾 גודל: {size_mb:.1f} MB")

    # יצירת תיקיית עבודה זמנית
    work_dir = tempfile.mkdtemp(prefix="video_edit_")
    print(f"📂 תיקיית עבודה: {work_dir}")

    # קובץ פלט
    base = Path(video_path)
    output_path = str(base.parent / f"{base.stem} - ערוך{base.suffix}")

    try:
        current_video = video_path

        # ===== שלב ההחלטה =====
        if silence_only:
            mode = "full"
            print("\n🎯 מצב: סרטון מלא נקי (הסרת שקטים בלבד)")
        elif topics_file:
            mode = "condensed"
            topics = load_topics(topics_file)
            print(f"\n🎯 מצב: סרטון מצומצם ({len(topics)} נושאים מקובץ)")
        else:
            # מצב אינטראקטיבי
            print("\n" + "=" * 60)
            print("🎯 מה את רוצה?")
            print("=" * 60)
            print("  [1] 🎬 סרטון מלא נקי — כל הנושאים, רק בלי שקטים")
            print("  [2] ✂️  סרטון מצומצם — בחירת נושאים + הסרת שקטים")

            choice = input("\nבחרי (1/2): ").strip()

            if choice == "2":
                mode = "condensed"
                # בדיקה אם יש קובץ נושאים
                default_topics = str(base.parent / f"{base.stem}_topics.json")
                if os.path.exists(default_topics):
                    print(f"\n📋 נמצא קובץ נושאים: {os.path.basename(default_topics)}")
                    topics = load_topics(default_topics)
                else:
                    print("\n⚠️  לא נמצא קובץ נושאים.")
                    print(f"   צרי קובץ JSON בשם: {os.path.basename(default_topics)}")
                    print("   או ציני נתיב עם --topics")

                    tp = input("\nנתיב לקובץ נושאים (או Enter לביטול): ").strip()
                    if tp and os.path.exists(tp):
                        topics = load_topics(tp)
                    else:
                        print("🔄 עוברת למצב סרטון מלא נקי")
                        mode = "full"
            else:
                mode = "full"
                print("\n🎯 מצב: סרטון מלא נקי")

        # ===== שלב חיתוך נושאים =====
        if mode == "condensed":
            selected = interactive_topic_selection(topics)
            if selected:
                # תיקון: תמיד חותכים לפי נושאים, גם אם כולם נבחרו.
                # הנושאים מגדירים קטעי KEEP — רווחים ביניהם הם מטא/בלאגן שצריך לחתוך.
                current_video = cut_by_topics(current_video, selected, work_dir)

                new_dur = get_video_duration(current_video)
                saved = duration - new_dur
                print(f"\n  ✅ אחרי חיתוך נושאים: {int(new_dur//60)}:{int(new_dur%60):02d}")
                print(f"  📉 נחסך: {int(saved//60)}:{int(saved%60):02d} דקות")
            else:
                print("\n  ℹ️  לא נבחרו נושאים — ממשיכה להסרת שקטים בלבד")

        # ===== שלב הסרת שקטים =====
        print("\n" + "=" * 60)
        print("🔇 שלב 2: הסרת שקטים")
        print("=" * 60)

        success = remove_silence(current_video, work_dir, output_path)

        if success and os.path.exists(output_path):
            final_dur = get_video_duration(output_path)
            final_size = os.path.getsize(output_path) / (1024 * 1024)
            total_saved = duration - final_dur

            print("\n" + "=" * 60)
            print("✅ סיום!")
            print("=" * 60)
            print(f"📁 קובץ פלט: {output_path}")
            print(f"⏱  אורך מקורי: {mins}:{secs:02d}")
            print(f"⏱  אורך סופי:  {int(final_dur//60)}:{int(final_dur%60):02d}")
            print(f"📉 נחסך: {int(total_saved//60)}:{int(total_saved%60):02d} דקות ({total_saved/duration*100:.1f}%)")
            print(f"💾 גודל: {size_mb:.1f} MB → {final_size:.1f} MB")
        else:
            print("\n❌ שגיאה ביצירת הקובץ הסופי")

    finally:
        # ניקוי תיקיית עבודה
        print(f"\n🧹 מנקה קבצים זמניים...")
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
