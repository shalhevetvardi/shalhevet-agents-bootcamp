#!/usr/bin/env python3
"""
transcribe_with_diarization.py
==============================
תמלול מחדש של הקלטות Twilio עם זיהוי דוברים (diarization) דרך ivrit.ai ב-RunPod.

מה הוא עושה:
  1. קורא את כל ההקלטות מ-Twilio (pagination, ללא lookback).
  2. לכל הקלטה: מוריד mp3 → שולח ל-RunPod עם transcribe_args.diarize=true.
  3. שומר תוצאה מלאה (segments + formatted_text) בקובץ JSON בתוך state/diarized/.
  4. לא נוגע ב-Airtable ולא בסקריפטים קיימים.

קרוא עם --help לרשימת פרמטרים.

הסקריפט הזה *לא* מחליף את modules/transcribe.py הקיים — הוא רץ בנפרד.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


# ─── הגדרות בסיס ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

with open(SCRIPT_DIR / "config.json", encoding="utf-8") as f:
    CONFIG = json.load(f)

STATE_DIR = SCRIPT_DIR / "state" / "diarized"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / "diarization.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("diarize")


# ─── עזרי ffmpeg/ffprobe (משכפל דפוסים מ-modules/transcribe.py) ─────────
def get_audio_duration_sec(path: str) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=60,
    ).decode().strip()
    return float(out)


def get_file_size_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def split_audio_by_time(path: str, chunk_sec: int, workdir: str) -> List[str]:
    ext = os.path.splitext(path)[1] or ".mp3"
    pattern = os.path.join(workdir, f"chunk_%03d{ext}")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", path,
            "-f", "segment",
            "-segment_time", str(chunk_sec),
            "-c", "copy",
            pattern,
        ],
        check=True, capture_output=True, timeout=600,
    )
    return sorted(
        os.path.join(workdir, f)
        for f in os.listdir(workdir)
        if f.startswith("chunk_")
    )


# ─── Twilio ─────────────────────────────────────────────────────────────
class TwilioClient:
    def __init__(self, sid: str, token: str):
        self.sid = sid
        self.auth = HTTPBasicAuth(sid, token)
        self.base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"

    def list_all_recordings(self) -> List[Dict[str, Any]]:
        """כל ה-recordings הזמינות בחשבון, ללא מגבלת זמן."""
        recordings: List[Dict[str, Any]] = []
        url = f"{self.base}/Recordings.json"
        params: Optional[Dict[str, Any]] = {"PageSize": 100}
        while url:
            r = requests.get(url, auth=self.auth, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            recordings.extend(data.get("recordings", []))
            next_uri = data.get("next_page_uri")
            url = f"https://api.twilio.com{next_uri}" if next_uri else None
            params = None
        return recordings

    def download_recording(self, rec_sid: str, target: str) -> str:
        r = requests.get(
            f"{self.base}/Recordings/{rec_sid}.mp3",
            auth=self.auth, timeout=120, stream=True,
        )
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return target


# ─── תמלול עם דיאריזציה דרך RunPod/ivrit.ai ─────────────────────────────
class DiarizedTranscriber:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        model: str = "ivrit-ai/whisper-large-v3-turbo-ct2",
        engine: str = "stable-whisper",
        max_mb: int = 6,
        chunk_sec: int = 917,
        retries: int = 3,
    ):
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.model = model
        self.engine = engine
        self.max_mb = max_mb
        self.chunk_sec = chunk_sec
        self.retries = retries
        self.base_url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    # ---- קריאה אחת ל-RunPod (chunk אחד) ----
    def _call_runpod(self, audio_path: str) -> Dict[str, Any]:
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        payload = {
            "input": {
                "engine": self.engine,
                "model": self.model,
                "transcribe_args": {
                    "blob": audio_b64,
                    "diarize": True,
                },
            }
        }

        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                r = requests.post(
                    f"{self.base_url}/runsync",
                    headers=self.headers, json=payload, timeout=1800,
                )
                r.raise_for_status()
                data = r.json()

                status = data.get("status")
                job_id = data.get("id")

                # polling אם RunPod דוחף לתור
                if status in ("IN_QUEUE", "IN_PROGRESS") and job_id:
                    log.info("  RunPod job %s is %s — polling...", job_id, status)
                    poll_url = f"{self.base_url}/status/{job_id}"
                    elapsed = 0
                    while elapsed < 1800:
                        time.sleep(5)
                        elapsed += 5
                        try:
                            pr = requests.get(poll_url, headers=self.headers, timeout=30)
                            pr.raise_for_status()
                            data = pr.json()
                        except requests.RequestException as e:
                            log.warning("  poll failed at %ds: %s", elapsed, e)
                            continue
                        status = data.get("status")
                        if status == "COMPLETED":
                            break
                        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                            raise RuntimeError(
                                f"RunPod {status}: {data.get('error')}"
                            )
                        if elapsed % 60 == 0:
                            log.info(
                                "  RunPod %s still %s (%ds)", job_id, status, elapsed
                            )
                    else:
                        raise RuntimeError(f"RunPod timeout at {status}")

                if data.get("status") != "COMPLETED":
                    raise RuntimeError(
                        f"RunPod {data.get('status')}: {data.get('error')}"
                    )
                return data.get("output", {})

            except Exception as e:
                last_err = e
                log.warning(
                    "  attempt %d/%d failed: %s", attempt, self.retries, e
                )
                if attempt < self.retries:
                    time.sleep(10 * attempt)

        assert last_err is not None
        raise last_err

    # ---- חילוץ סגמנטים ממבני output שונים ----
    @staticmethod
    def _extract_segments(output: Any) -> List[Dict[str, Any]]:
        """
        ivrit.ai RunPod handler יכול להחזיר במבנים שונים לפי גרסה.
        אנחנו עוברים רקורסיבית ואוספים סגמנטים עם text ו-start/end.
        """
        segments: List[Dict[str, Any]] = []
        seen_ids = set()

        def add(seg):
            key = (seg.get("start"), seg.get("end"), seg.get("text"))
            if key in seen_ids:
                return
            seen_ids.add(key)
            segments.append(seg)

        def walk(node):
            if isinstance(node, dict):
                # סגמנט עם text + start/end ← מועמד אמיתי
                if (
                    isinstance(node.get("text"), str)
                    and ("start" in node or "end" in node)
                ):
                    add(node)
                # פורמטים מורכבים
                if isinstance(node.get("segments"), list):
                    walk(node["segments"])
                if "result" in node:
                    walk(node["result"])
                if node.get("type") == "segments" and isinstance(
                    node.get("data"), (list, dict)
                ):
                    walk(node["data"])
                # מסלול נוסף: data בלי type
                elif isinstance(node.get("data"), list):
                    walk(node["data"])
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            else:
                # dataclass Segment
                if getattr(node, "text", None) and getattr(node, "start", None) is not None:
                    add(
                        {
                            "start": getattr(node, "start", None),
                            "end": getattr(node, "end", None),
                            "text": getattr(node, "text", ""),
                            "speaker": getattr(node, "speaker", None),
                        }
                    )

        result = output.get("result", output) if isinstance(output, dict) else output
        walk(result)
        return segments

    # ---- תמלול מלא (עם chunking אם צריך) ----
    def transcribe(self, audio_path: str) -> Dict[str, Any]:
        size_mb = get_file_size_mb(audio_path)
        log.info("  transcribing %.1f MB (engine=%s)", size_mb, self.engine)

        if size_mb <= self.max_mb:
            output = self._call_runpod(audio_path)
            segments = self._extract_segments(output)
            return {
                "segments": segments,
                "engine": self.engine,
                "model": self.model,
                "num_chunks": 1,
            }

        duration = get_audio_duration_sec(audio_path)
        num_chunks = math.ceil(duration / self.chunk_sec)
        log.info(
            "  file too large — splitting to %d chunks of %ds",
            num_chunks, self.chunk_sec,
        )

        all_segments: List[Dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="diar_chunks_") as workdir:
            chunks = split_audio_by_time(audio_path, self.chunk_sec, workdir)
            for i, chunk in enumerate(chunks):
                offset = i * self.chunk_sec
                log.info("  chunk %d/%d (offset=%ds)", i + 1, len(chunks), offset)
                try:
                    output = self._call_runpod(chunk)
                    segs = self._extract_segments(output)
                    for s in segs:
                        if isinstance(s.get("start"), (int, float)):
                            s["start"] = float(s["start"]) + offset
                        if isinstance(s.get("end"), (int, float)):
                            s["end"] = float(s["end"]) + offset
                        s["_chunk"] = i
                    all_segments.extend(segs)
                except Exception as e:
                    log.exception("  chunk %d failed: %s", i + 1, e)
                    all_segments.append({
                        "_chunk_error": True,
                        "_chunk": i,
                        "error": str(e),
                    })
        return {
            "segments": all_segments,
            "engine": self.engine,
            "model": self.model,
            "num_chunks": len(chunks),
        }


# ─── פורמוט לטקסט קריא ─────────────────────────────────────────────────
def _fmt_ts(sec: Optional[float]) -> str:
    if sec is None:
        return "??:??"
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _extract_speaker(seg: Dict[str, Any]) -> Optional[str]:
    """
    חולץ מזהה דובר ממקטע. ה-handler של ivrit.ai מחזיר את הדוברים בשדה
    `speakers` כרשימה (למשל ['SPEAKER_00']). יש גרסאות/engines אחרים
    שמחזירים `speaker` (יחיד). הפונקציה תומכת בשני המבנים.
    """
    sp_list = seg.get("speakers")
    if isinstance(sp_list, list) and sp_list:
        return str(sp_list[0])
    if isinstance(sp_list, str) and sp_list:
        return sp_list
    sp_single = seg.get("speaker")
    if sp_single:
        return str(sp_single)
    return None


def format_for_humans(segments: List[Dict[str, Any]]) -> str:
    """
    ממזג רצפים של אותו דובר ומפיק פורמט:

        [00:00 → 00:03 | דובר 0]
        שלום, מה שלומך?

        [00:03 → 00:05 | דובר 1]
        בסדר, תודה...
    """
    lines: List[str] = []
    cur_speaker: Optional[str] = None
    cur_start: Optional[float] = None
    cur_end: Optional[float] = None
    buf: List[str] = []

    def flush():
        if not buf:
            return
        sp_raw = cur_speaker
        if sp_raw is None:
            sp_label = "לא זוהה"
        else:
            # SPEAKER_00 / SPEAKER_01 → דובר 0 / דובר 1
            digits = "".join(c for c in str(sp_raw) if c.isdigit())
            sp_label = f"דובר {int(digits)}" if digits else str(sp_raw)
        header = f"[{_fmt_ts(cur_start)} → {_fmt_ts(cur_end)} | {sp_label}]"
        lines.append(header)
        lines.append(" ".join(buf).strip())
        lines.append("")

    for s in segments:
        if s.get("_chunk_error"):
            flush()
            buf.clear()
            cur_speaker = None
            lines.append(f"[⚠️ שגיאה ב-chunk {s.get('_chunk')}: {s.get('error','')}]")
            lines.append("")
            continue

        text = (s.get("text") or "").strip()
        if not text:
            continue
        speaker = _extract_speaker(s)
        start = float(s.get("start", 0) or 0)
        end = float(s.get("end", start) or start)

        if speaker != cur_speaker:
            flush()
            buf = [text]
            cur_speaker = speaker
            cur_start = start
        else:
            buf.append(text)
        cur_end = end

    flush()
    return "\n".join(lines).strip()


# ─── עיבוד הקלטה בודדת ───────────────────────────────────────────────
def process_one(
    twilio: TwilioClient,
    transcriber: DiarizedTranscriber,
    rec: Dict[str, Any],
    idx: int,
    total: int,
    skip_done: bool,
    min_duration_sec: float = 30.0,
) -> Dict[str, Any]:
    """מעבד הקלטה אחת. מחזיר dict עם סטטוס."""
    rec_sid = rec.get("sid")
    call_sid = rec.get("call_sid")

    if not rec_sid or not call_sid:
        log.warning("[%d/%d] missing sid", idx, total)
        return {"status": "missing_sid"}

    try:
        dur = float(rec.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0

    if dur and dur < min_duration_sec:
        log.info(
            "[%d/%d] skip short %.0fs call_sid=%s",
            idx, total, dur, call_sid,
        )
        return {"status": "skip_short", "call_sid": call_sid}

    out_path = STATE_DIR / f"{call_sid}.json"
    if skip_done and out_path.exists():
        log.info("[%d/%d] already done call_sid=%s", idx, total, call_sid)
        return {"status": "skip_done", "call_sid": call_sid}

    log.info(
        "[%d/%d] → call_sid=%s rec_sid=%s dur=%.0fs",
        idx, total, call_sid, rec_sid, dur,
    )

    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            audio_path = tmp.name
        twilio.download_recording(rec_sid, audio_path)
        size_mb = os.path.getsize(audio_path) / 1024 / 1024
        log.info("  downloaded %.1f MB", size_mb)

        result = transcriber.transcribe(audio_path)
    except Exception as e:
        log.exception("[%d/%d] FAILED call_sid=%s: %s", idx, total, call_sid, e)
        return {"status": "error", "call_sid": call_sid, "error": str(e)}
    finally:
        if audio_path:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

    segments = result.get("segments", [])
    speakers = sorted(
        {sp for s in segments if (sp := _extract_speaker(s))}
    )
    formatted = format_for_humans(segments)

    payload = {
        "call_sid": call_sid,
        "recording_sid": rec_sid,
        "duration_sec": dur,
        "date_created": rec.get("date_created"),
        "engine": result.get("engine"),
        "model": result.get("model"),
        "num_chunks": result.get("num_chunks"),
        "num_segments": len([s for s in segments if not s.get("_chunk_error")]),
        "num_chunk_errors": len([s for s in segments if s.get("_chunk_error")]),
        "speakers_detected": speakers,
        "segments": segments,
        "formatted_text": formatted,
        "transcribed_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log.info(
        "  ✓ %d segments | %d speakers | → %s",
        payload["num_segments"], len(speakers), out_path.name,
    )
    return {
        "status": "ok",
        "call_sid": call_sid,
        "num_segments": payload["num_segments"],
        "speakers": speakers,
    }


# ─── main ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None,
                    help="הגבלת מספר הקלטות לעיבוד (לבדיקה)")
    ap.add_argument("--only-call-sids", nargs="+", default=None,
                    help="רק Call SIDs ספציפיים")
    ap.add_argument("--engine", default="stable-whisper",
                    choices=["stable-whisper", "faster-whisper"],
                    help="engine ב-RunPod (ברירת מחדל: stable-whisper לתמיכה בדיאריזציה)")
    ap.add_argument("--retry-done", action="store_true",
                    help="עבד שוב גם הקלטות שכבר יש להן קובץ JSON (דריסה)")
    ap.add_argument("--min-duration-sec", type=float, default=30.0,
                    help="דילוג על הקלטות קצרות מזה (ברירת מחדל 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="הצג מה היה מעובד בלי להוריד/לתמלל")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("Diarization run started at %s", datetime.now().isoformat())
    log.info(
        "args: engine=%s limit=%s only=%s retry=%s dry=%s",
        args.engine, args.limit, args.only_call_sids, args.retry_done, args.dry_run,
    )

    twilio = TwilioClient(
        sid=os.environ["TWILIO_ACCOUNT_SID"],
        token=os.environ["TWILIO_AUTH_TOKEN"],
    )
    transcriber = DiarizedTranscriber(
        api_key=os.environ["RUNPOD_API_KEY"],
        endpoint_id=os.environ["RUNPOD_ENDPOINT_ID"],
        model=CONFIG["transcription"]["model_path"],
        engine=args.engine,
        max_mb=CONFIG["transcription"]["max_audio_size_mb"],
        chunk_sec=CONFIG["transcription"]["chunk_duration_seconds"],
    )

    log.info("Fetching recordings from Twilio (no lookback)...")
    recordings = twilio.list_all_recordings()
    log.info("Found %d total recordings", len(recordings))

    if args.only_call_sids:
        wanted = set(args.only_call_sids)
        recordings = [r for r in recordings if r.get("call_sid") in wanted]
        log.info("Filtered to %d by --only-call-sids", len(recordings))

    if args.limit:
        recordings = recordings[: args.limit]
        log.info("Limited to first %d", args.limit)

    if args.dry_run:
        log.info("DRY RUN — would process:")
        for i, r in enumerate(recordings, 1):
            log.info(
                "  [%d] call_sid=%s rec_sid=%s dur=%s date=%s",
                i, r.get("call_sid"), r.get("sid"),
                r.get("duration"), r.get("date_created"),
            )
        return

    stats = {"ok": 0, "skip_done": 0, "skip_short": 0, "error": 0, "missing_sid": 0}
    total = len(recordings)
    for i, rec in enumerate(recordings, 1):
        try:
            result = process_one(
                twilio, transcriber, rec, i, total,
                skip_done=not args.retry_done,
                min_duration_sec=args.min_duration_sec,
            )
            stats[result["status"]] = stats.get(result["status"], 0) + 1
        except Exception as e:
            log.exception("[%d/%d] unexpected error: %s", i, total, e)
            stats["error"] += 1

    log.info("=" * 60)
    log.info("Done. stats: %s", stats)
    log.info("Outputs in: %s", STATE_DIR)
    log.info("Log file: %s", LOG_PATH)


if __name__ == "__main__":
    main()
