#!/usr/bin/env python3
"""Transcribe 2 unmatched recordings using the pipeline's IvritTranscriber."""

import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

sys.path.insert(0, os.path.dirname(__file__))
from modules.transcribe import IvritTranscriber

transcriber = IvritTranscriber(
    runpod_api_key=os.environ["RUNPOD_API_KEY"],
    runpod_endpoint_id=os.environ["RUNPOD_ENDPOINT_ID"],
)

files = [
    ("/tmp/unmatched_calls/RE35f5c3491271912cb3aa68eea0458d55.mp3",
     "CA66f3783b2fcae582310f6f99d878b7f2", "17:21 ISR, 2 min"),
    ("/tmp/unmatched_calls/RE5a8dc37827e0938b86630933b90e4e48.mp3",
     "CA0646ef03e835b94d72ab6859be18124c", "16:35 ISR, 52 sec"),
]

for path, call_sid, desc in files:
    print(f"\n{'='*60}")
    print(f"Call: {call_sid}")
    print(f"Time: {desc}")
    print(f"{'='*60}")
    transcript = transcriber.transcribe(path)
    print(transcript)
    print()
