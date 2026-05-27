"""
תמלול עברית עם ivrit.ai דרך RunPod Serverless.
משכפל את הדפוסים המוכחים מ-zoom_pipeline.py:
- path= (לא url=)
- chunking לפי זמן (917 שניות) לקבצים > 6MB
- טיפול ב-Segment dataclass (isinstance check)
"""
import os
import math
import time
import base64
import logging
import subprocess
import tempfile
from typing import Optional, Tuple
import requests

log = logging.getLogger(__name__)


def get_audio_duration_sec(audio_path: str) -> float:
    """שולף את משך הקובץ בשניות דרך ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    out = subprocess.check_output(cmd, timeout=60).decode().strip()
    return float(out)


def get_file_size_mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def split_audio_by_time(audio_path: str, chunk_sec: int, workdir: str) -> list:
    """
    מחלק אודיו ל-chunks של chunk_sec שניות ב-ffmpeg.
    מחזיר רשימה של נתיבים.
    """
    ext = os.path.splitext(audio_path)[1] or ".mp3"
    pattern = os.path.join(workdir, f"chunk_%03d{ext}")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "segment",
        "-segment_time", str(chunk_sec),
        "-c", "copy",
        pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    chunks = sorted(
        [os.path.join(workdir, f) for f in os.listdir(workdir) if f.startswith("chunk_")]
    )
    return chunks


class IvritTranscriber:
    def __init__(self, runpod_api_key: str, runpod_endpoint_id: str, max_mb: int = 6, chunk_sec: int = 917):
        self.api_key = runpod_api_key
        self.endpoint_id = runpod_endpoint_id
        self.max_mb = max_mb
        self.chunk_sec = chunk_sec
        self.base_url = f"https://api.runpod.ai/v2/{runpod_endpoint_id}"
        self.headers = {
            "Authorization": f"Bearer {runpod_api_key}",
            "Content-Type": "application/json",
        }

    def _transcribe_chunk(self, audio_path: str) -> str:
        """שולח קובץ אחד ל-RunPod ומחזיר טקסט."""
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        # פורמט חדש של ivrit.ai RunPod handler:
        # input.engine + input.model + input.transcribe_args.blob
        payload = {
            "input": {
                "engine": "faster-whisper",
                "model": "ivrit-ai/whisper-large-v3-turbo-ct2",
                "transcribe_args": {
                    "blob": audio_b64,
                },
            }
        }

        # runsync — ממתין לתשובה (עד 30 דקות).
        # לפעמים RunPod מחזיר IN_QUEUE/IN_PROGRESS גם מ-runsync כשהתור עמוס —
        # במקרה כזה נעבור ל-polling על /status/{id}.
        r = requests.post(
            f"{self.base_url}/runsync",
            headers=self.headers,
            json=payload,
            timeout=1800,
        )
        r.raise_for_status()
        data = r.json()

        status = data.get("status")
        job_id = data.get("id")

        # אם לא הסתיים מיידית — polling עד 30 דקות
        if status in ("IN_QUEUE", "IN_PROGRESS") and job_id:
            log.info("RunPod job %s is %s — polling /status...", job_id, status)
            poll_url = f"{self.base_url}/status/{job_id}"
            max_wait_sec = 1800  # 30 דקות
            interval_sec = 5
            elapsed = 0
            while elapsed < max_wait_sec:
                time.sleep(interval_sec)
                elapsed += interval_sec
                try:
                    pr = requests.get(poll_url, headers=self.headers, timeout=30)
                    pr.raise_for_status()
                    data = pr.json()
                except requests.RequestException as e:
                    log.warning("Polling request failed at %d sec: %s — retrying", elapsed, e)
                    continue
                status = data.get("status")
                if status == "COMPLETED":
                    log.info("RunPod job %s completed after %d sec", job_id, elapsed)
                    break
                if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    log.error("RunPod job %s ended with status %s: %s", job_id, status, data)
                    raise RuntimeError(
                        f"RunPod status: {status}, error: {data.get('error')}"
                    )
                # הדפסה כל 30 שניות כדי לא להציף את הלוג
                if elapsed % 30 == 0:
                    log.info("RunPod job %s still %s (%d sec elapsed)", job_id, status, elapsed)
            else:
                log.error("RunPod job %s timed out after %d sec (last status: %s)", job_id, max_wait_sec, status)
                raise RuntimeError(
                    f"RunPod timeout: job {job_id} stuck at {status} after {max_wait_sec} sec"
                )

        if data.get("status") != "COMPLETED":
            log.error("RunPod job failed: %s", data)
            raise RuntimeError(f"RunPod status: {data.get('status')}, error: {data.get('error')}")

        output = data.get("output", {})

        # תאימות לאחור/קדימה:
        # חלק מה-handler-ים מחזירים output.result, אחרים מחזירים output ישירות.
        result = output.get("result", output) if isinstance(output, dict) else output

        segments = []

        def collect_segments(node):
            """חילוץ רקורסיבי של segmentים ממבני output שונים של RunPod/ivrit."""
            if isinstance(node, dict):
                # segment קלאסי
                if isinstance(node.get("text"), str):
                    segments.append(node)

                # פורמט ותיק: {"segments": [...]}
                seg_list = node.get("segments")
                if isinstance(seg_list, list):
                    collect_segments(seg_list)

                # פורמט נפוץ חדש: {"result": ...}
                if "result" in node:
                    collect_segments(node.get("result"))

                # פורמט event-stream: {"type":"segments","data":[...]}
                node_type = node.get("type")
                node_data = node.get("data")
                if node_type == "segments":
                    collect_segments(node_data)
                elif isinstance(node_data, (list, dict)):
                    collect_segments(node_data)

            elif isinstance(node, list):
                for item in node:
                    collect_segments(item)
            else:
                # תאימות לדפוס Segment dataclass object
                if getattr(node, "text", None):
                    segments.append(node)

        if isinstance(result, dict) and isinstance(result.get("text"), str):
            return result["text"]
        collect_segments(result)

        # איחוד הסגמנטים — טיפול בדפוס Segment dataclass
        parts = []
        for seg in segments:
            if isinstance(seg, dict):
                text = seg.get("text", "")
            else:
                # Segment dataclass object
                text = getattr(seg, "text", "")
            if text:
                parts.append(text.strip())

        transcript = " ".join(parts).strip()
        if not transcript:
            log.error("RunPod completed but transcript is empty. output=%s", output)
        return transcript

    def transcribe(self, audio_path: str) -> str:
        """
        מתמלל קובץ אודיו. אם גדול מ-max_mb — מחלק ל-chunks.
        """
        size_mb = get_file_size_mb(audio_path)
        log.info("Transcribing %s (%.1f MB)", audio_path, size_mb)

        if size_mb <= self.max_mb:
            return self._transcribe_chunk(audio_path)

        # חישוב chunks לפי זמן
        duration = get_audio_duration_sec(audio_path)
        num_chunks = math.ceil(duration / self.chunk_sec)
        log.info(
            "File too large (%.1f MB > %d MB). Splitting into %d chunks of %d sec.",
            size_mb, self.max_mb, num_chunks, self.chunk_sec,
        )

        with tempfile.TemporaryDirectory(prefix="ivrit_chunks_") as workdir:
            chunks = split_audio_by_time(audio_path, self.chunk_sec, workdir)
            log.info("Created %d chunks", len(chunks))
            parts = []
            for i, chunk in enumerate(chunks, 1):
                log.info("Transcribing chunk %d/%d (%.1f MB)", i, len(chunks), get_file_size_mb(chunk))
                try:
                    part = self._transcribe_chunk(chunk)
                    parts.append(part)
                except Exception as e:
                    log.exception("Chunk %d failed: %s", i, e)
                    parts.append(f"[chunk {i} failed]")
            return "\n".join(parts).strip()
