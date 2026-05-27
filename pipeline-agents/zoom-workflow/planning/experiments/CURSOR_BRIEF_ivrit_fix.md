# בריף לקרסר — תיקון באג 8 של ivrit.ai ב-Zoom Workflow

## 🎯 מה צריך לעשות

להחליף את מנגנון התמלול ב-`zoom_pipeline.py` מהשימוש הישן ב-SDK של `ivrit` לקריאת HTTP ישירה ל-RunPod עם פורמט payload חדש. זהו באג מתועד (#8, אפריל 2026) שכבר תוקן בפייפליין אחר (שיחות מכירה במחשב a97254) אבל לא הופעל פה.

**חשוב:** לשמור על חתימות הפונקציות הקיימות (`transcribe_audio`, `_transcribe_single`) ועל פורמט הפלט — שאר הפייפליין תלוי בהן.

---

## 📁 נתיבים של כל דבר

### מחשב (shalhevet)
| תיאור | נתיב |
|---|---|
| תיקיית הקוד | `~/Applications/zoom-workflow/` |
| הקובץ לעריכה | `~/Applications/zoom-workflow/zoom_pipeline.py` |
| Config | `~/Applications/zoom-workflow/config.json` |
| דוגמה לתיקון (הועלה מה-a97254) | `~/Applications/zoom-workflow/transcribe.py` (או איפה שהיא תשים אותו) |
| פרומפטים | `~/Applications/zoom-workflow/prompts/` |
| לוג ראשי | `~/Applications/zoom-workflow/watcher.log` |
| לוג שגיאות | `~/Applications/zoom-workflow/watcher_stderr.log` |
| דימון (רץ ברקע) | `~/Applications/zoom-workflow/bash_watcher_daemon.sh` |
| לונצ'ר | `~/Applications/zoom-workflow/bash_watcher.command` |
| תיקיית הקלטות Zoom | `/Users/shalhevet/Documents/Zoom` |
| Staging זמני | `~/Applications/zoom-workflow/staging/` |
| processed files | `~/Applications/zoom-workflow/processed_files.json` |

### שורות רלוונטיות ב-`zoom_pipeline.py` (מצב לפני התיקון)
- **שורה 29** — `import ivrit` (הייבוא של ה-SDK הישן — צריך להישאר או להיעלם לפי איך שמיישמים)
- **שורות 250-308** — `_split_audio` (מפצל קבצים גדולים עם ffmpeg) — **לא צריך לגעת**
- **שורות 311-379** — `_transcribe_single` — **המוקד של התיקון**
- **שורות 382-457** — `transcribe_audio` — **בעיקר לא צריך לגעת** (wrapper שמחליט אם לפצל)
- **שורות 560-600** — `format_transcript_with_timestamps` — **לא צריך לגעת** (הצרכן של `words`)
- **שורה 2173** — נקודת הקריאה: `transcription = transcribe_audio(read_path, client, config, logger)` — חייב להמשיך לעבוד בלי שינוי
- **שורה 2210** — `words = transcription.get("words", [])` — הצרכן של `words`

---

## 🔧 מה בדיוק צריך להחליף

### 1. פונקציה `_transcribe_single` (שורות 311-379)

**עכשיו** (לא עובד — מחזיר 404 ו-ConnectionResetError):
```python
model = ivrit.load_model(
    engine="runpod",
    model="ivrit-ai/whisper-large-v3-turbo-ct2",
    api_key=runpod_api_key,
    endpoint_id=runpod_endpoint_id
)
result = model.transcribe(path=audio_path)
```

**הפורמט החדש (מתוך `transcribe.py` של a97254):**
```python
import base64, requests, time

with open(audio_path, "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

payload = {
    "input": {
        "engine": "faster-whisper",
        "model": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "transcribe_args": {
            "blob": audio_b64,
        },
    }
}

base_url = f"https://api.runpod.ai/v2/{runpod_endpoint_id}"
headers = {
    "Authorization": f"Bearer {runpod_api_key}",
    "Content-Type": "application/json",
}

r = requests.post(f"{base_url}/runsync", headers=headers, json=payload, timeout=1800)
r.raise_for_status()
data = r.json()
```

**טיפול ב-`IN_QUEUE`/`IN_PROGRESS`** (polling עד 30 דקות):
```python
status = data.get("status")
job_id = data.get("id")

if status in ("IN_QUEUE", "IN_PROGRESS") and job_id:
    poll_url = f"{base_url}/status/{job_id}"
    max_wait_sec = 1800  # 30 דקות
    interval_sec = 5
    elapsed = 0
    while elapsed < max_wait_sec:
        time.sleep(interval_sec)
        elapsed += interval_sec
        try:
            pr = requests.get(poll_url, headers=headers, timeout=30)
            pr.raise_for_status()
            data = pr.json()
        except requests.RequestException as e:
            logger.warning(f"Polling failed at {elapsed}s: {e}")
            continue
        status = data.get("status")
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RuntimeError(f"RunPod {status}: {data.get('error')}")
    else:
        raise RuntimeError(f"RunPod timeout at {status} after {max_wait_sec}s")

if data.get("status") != "COMPLETED":
    raise RuntimeError(f"RunPod status: {data.get('status')}, error: {data.get('error')}")
```

### 2. Parser לפלט — עם תמיכה ב-`words` (הרחבה על `transcribe.py`)

הקובץ `transcribe.py` שהעלינו מחזיר **רק טקסט** אבל `zoom_pipeline.py` דורש גם `words` עם word-level timestamps. צריך להרחיב את `collect_segments` שיעשה גם חילוץ words.

```python
output = data.get("output", {})
result = output.get("result", output) if isinstance(output, dict) else output

segments = []

def collect_segments(node):
    if isinstance(node, dict):
        if isinstance(node.get("text"), str) and ("start" in node or "words" in node or "end" in node):
            segments.append(node)
        seg_list = node.get("segments")
        if isinstance(seg_list, list):
            collect_segments(seg_list)
        if "result" in node:
            collect_segments(node.get("result"))
        if node.get("type") == "segments":
            collect_segments(node.get("data"))
        elif isinstance(node.get("data"), (list, dict)):
            collect_segments(node.get("data"))
    elif isinstance(node, list):
        for item in node:
            collect_segments(item)

collect_segments(result)

# בניית הפלט בפורמט שה-pipeline מצפה לו
transcript_parts = []
words = []

for seg in segments:
    if isinstance(seg, dict):
        seg_text = seg.get("text", "")
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        seg_words = seg.get("words", [])
    else:
        seg_text = getattr(seg, "text", "")
        seg_start = getattr(seg, "start", 0)
        seg_end = getattr(seg, "end", 0)
        seg_words = getattr(seg, "words", []) or []

    if seg_text:
        transcript_parts.append(seg_text.strip())

    if seg_words:
        for w in seg_words:
            if isinstance(w, dict):
                words.append({
                    "word": w.get("word", ""),
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                })
            else:
                words.append({
                    "word": getattr(w, "word", ""),
                    "start": getattr(w, "start", 0),
                    "end": getattr(w, "end", 0),
                })
    else:
        # fallback: segment כ"מילה" אחת
        words.append({
            "word": seg_text.strip(),
            "start": seg_start,
            "end": seg_end,
        })

# fallback אחרון: אם result הוא dict עם text ישיר
if not transcript_parts and isinstance(result, dict) and isinstance(result.get("text"), str):
    transcript_parts = [result["text"]]

transcript_text = " ".join(transcript_parts).strip()

if not transcript_text:
    logger.error(f"RunPod completed but transcript empty. output={output}")
    return None

return {
    "transcript": transcript_text,
    "words": words,
    "whisper_language": result.get("language", "unknown") if isinstance(result, dict) else "unknown",
}
```

### 3. מה **אסור** לשנות

🚫 חתימות פונקציות:
- `_transcribe_single(audio_path, client, config, logger) -> Optional[dict]`
- `transcribe_audio(audio_path, client, config, logger) -> Optional[dict]`

🚫 פורמט הפלט של הפונקציות:
```python
{
    "transcript": str,
    "words": [{"word": str, "start": float, "end": float}, ...],
    "whisper_language": str,
}
```

🚫 `_split_audio` (שורות 252-308) — ffmpeg chunking של קבצים > 6MB עובד. לא לגעת.

🚫 `transcribe_audio` (שורות 382-457) — ה-orchestrator שמחליט אם לפצל. רק ה-inner call ל-`_transcribe_single` משתנה. לא לגעת במבנה של ה-time_offset, ה-loop על chunks, וה-shutil.rmtree בסוף.

🚫 `config.json` — לא לגעת. `runpod_api_key`, `runpod_endpoint_id`, `max_audio_size_mb: 6` — הכל מוגדר נכון.

---

## ✅ איך בודקים שזה עובד

### שלב 1: syntax check
```bash
cd ~/Applications/zoom-workflow
python3 -m py_compile zoom_pipeline.py
```
(צריך לצאת בלי שגיאות)

### שלב 2: הרצה על קובץ קטן (יש כבר אחד כושל בלוג)
```bash
cd ~/Applications/zoom-workflow
python3 zoom_pipeline.py --file "/Users/shalhevet/Documents/Zoom/2026-04-17 16.42.18 אימפרוב בינה מלאכותית's Zoom Meeting/audio1925112716.m4a"
```

**מה לצפות לראות בלוג:**
- `מתמלל: audio1925112716.m4a (0.1MB)` — התחלה
- לא `404 Client Error` ולא `Connection reset by peer`
- `תמלול הושלם: XX תווים, YY מילים עם timestamps`
- `נשמר ב-Notion: https://www.notion.so/...`

### שלב 3: אימות ב-Notion
לפתוח את הדאטאבייס [תמלולים](https://www.notion.so/ed135505c9144b2c86ff49ed3c767af0) ולוודא:
- שורה חדשה נוצרה
- סטטוס "הצלחה" (לא "שגיאה")
- יש תמלול (לא ריק)

### שלב 4: הפעלה מחדש של הדימון
```bash
pkill -f bash_watcher_daemon.sh
# ואז דאבל-קליק על bash_watcher.command
ps aux | grep bash_watcher_daemon  # לוודא שרץ
```

### שלב 5: מעקב בלוג
```bash
tail -f ~/Applications/zoom-workflow/watcher.log
```

---

## 🧨 סיכונים ונקודות לשים אליהן לב

1. **הקובץ `audio1924399273.m4a` (74MB, 9 chunks) — נכשל כולו בלוג הקודם.** ה-`processed_files.json` כבר מסומן שעובד עם סטטוס שגיאה. אם רוצים לנסות שוב — להשתמש ב-`retranscribe_failed.sh` או `retranscribe_all_failed.sh` שכבר קיימים בתיקייה.

2. **חלק מה-handlers של RunPod מחזירים `output.result`, חלק מחזירים `output` ישירות.** הקוד החדש מטפל בשניהם (`output.get("result", output)`).

3. **אל תשכחו להסיר את `import ivrit`** אם הוא לא בשימוש אחרי התיקון — כדי שלא יקרוס אם הספרייה תימחק.

4. **`requests` כבר מיובא** בראש הקובץ (שורה ~27) — לא צריך להוסיף.

5. **`base64` ו-`time` לא מיובאים כברירת מחדל.** צריך להוסיף `import base64` ו-`import time` ל-imports בראש הקובץ (`time` אולי כבר שם — לבדוק).

6. **השגיאה הקודמת `404 Not Found for url: https://api.runpod.ai/v2/xhgwahvo4euqp8/run`** — שימו לב שבקוד החדש משתמשים ב-`/runsync` (לא `/run`). זה בכוונה — `/runsync` ממתין לתשובה; `/run` היה async.

---

## 📚 הקשר (לא חובה לקרוא, רק אם צריך רקע)

- **התיעוד המרכזי בנושן:** [אוטומציות - תיעוד](https://www.notion.so/31b13b4c3d7880b58287d992129fd82b) — שם מתוארים כל 8 הבאגים ההיסטוריים של הפייפליין
- **באגים 5-6 (מרץ 2026)** — תוקנו בעבר (url→path, Segment dataclass). הקוד הנוכחי כבר מטפל בהם נכון
- **באג 8 (אפריל 2026)** — זה מה שאנחנו מתקנים עכשיו
- **פייפליין דומה שכבר תוקן:** שיחות מכירה במחשב a97254 (הקובץ `transcribe.py` שהועלה הוא משם)
- **פייפליין נוסף שעוד לא תוקן:** Podcast Clip Pipeline v5 — אותה בעיה, אבל לא בטיפול עכשיו

---

## 🎬 סיכום בשלושה משפטים

1. מחליפים `ivrit.load_model(...).transcribe(path=...)` בקריאת HTTP ישירה ל-`https://api.runpod.ai/v2/{endpoint}/runsync` עם payload `{"input": {"engine": "faster-whisper", "model": "ivrit-ai/whisper-large-v3-turbo-ct2", "transcribe_args": {"blob": <base64>}}}`.
2. מוסיפים polling ל-`/status/{id}` למקרה שמחזירים `IN_QUEUE`/`IN_PROGRESS`, ו-parser רקורסיבי שמחלץ `segments` + `words` ממבני output שונים.
3. שומרים על חתימת `_transcribe_single`/`transcribe_audio` ועל הפלט `{"transcript", "words", "whisper_language"}` — כדי ששאר הפייפליין (format_transcript_with_timestamps, run_target_prompt, save_to_notion) ימשיך לעבוד בלי שינוי.
