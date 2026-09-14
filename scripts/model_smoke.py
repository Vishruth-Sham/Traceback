#!/usr/bin/env python3
"""Synthetic runtime smoke check for the transcription/interpretation adapters.

Uses macOS `say` + `afconvert` to synthesize speech (no microphone capture)
and a fixed synthetic text capture, then runs both adapters and reports
latency, peak memory where feasible, and the actual model tag/digest used.
This is a runtime smoke check, not a personal-recording quality benchmark:
see docs/local-models.md for the explicit caveat this script's output backs.
"""

import json
import resource
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.config import get_settings
from processor.interpretation import interpret
from processor.transcription import transcribe

SYNTHETIC_UTTERANCE = "Buy milk tomorrow and finish the capture endpoint by five p m for Traceback"
SYNTHETIC_TEXT_CAPTURE = "Note to self: read the second chapter of the book on distributed systems this weekend."


def synthesize_audio(tmp_dir: Path) -> Path:
    aiff_path = tmp_dir / "smoke.aiff"
    wav_path = tmp_dir / "smoke.wav"
    subprocess.run(["say", "-o", str(aiff_path), SYNTHETIC_UTTERANCE], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff_path), str(wav_path)], check=True)
    return wav_path


def ollama_model_report(model: str) -> dict:
    listed = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
    digest = None
    for line in listed.stdout.splitlines()[1:]:
        parts = line.split()
        if parts and parts[0] == model:
            digest = parts[1]
            break
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=30)
    return {"model": model, "digest": digest, "ps": ps.stdout.strip()}


def main() -> int:
    settings = get_settings()
    report: dict = {"whisper_model_path": str(settings.whisper_model_path), "ollama_model": settings.ollama_model}

    with tempfile.TemporaryDirectory(prefix="traceback-smoke-") as tmp:
        tmp_dir = Path(tmp)
        print("Synthesizing speech fixture with `say` (no microphone used)...")
        wav_path = synthesize_audio(tmp_dir)

        start = time.time()
        transcript = transcribe(wav_path, settings=settings)
        transcribe_latency = time.time() - start
        # ru_maxrss is a high-water mark across all reaped children in this process,
        # not just whisper-cli, but this script reaps no other children before this point.
        child_peak_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        report["transcription"] = {
            "input": SYNTHETIC_UTTERANCE,
            "output": transcript,
            "latency_s": round(transcribe_latency, 3),
            "child_peak_rss_bytes": child_peak_rss,
            "note": "First call on a machine pays a one-time Metal shader compile cost; "
            "this run may be cold or warm depending on prior invocations.",
        }
        print(f"Transcript: {transcript!r} ({transcribe_latency:.2f}s)")

        cat_id = str(uuid.uuid4())
        context = {
            "captured_at": "2026-09-14T09:00:00+05:30",
            "source_timezone": "Asia/Kolkata",
            "source_date": "2026-09-14",
            "categories": [{"id": cat_id, "slug": "projects", "name": "Projects"}],
        }
        for label, text in (("voice_transcript", transcript), ("typed_text", SYNTHETIC_TEXT_CAPTURE)):
            start = time.time()
            proposal = interpret(text, context, settings=settings)
            latency = time.time() - start
            report.setdefault("interpretation", {})[label] = {
                "input": text,
                "output": proposal,
                "latency_s": round(latency, 3),
            }
            print(f"[{label}] interpreted in {latency:.2f}s: {json.dumps(proposal)}")

        report["ollama"] = ollama_model_report(settings.ollama_model)

    print("\n--- Summary (JSON) ---")
    print(json.dumps(report, indent=2, default=str))
    print(
        "\nThis smoke check used synthetic text/audio fixtures only. It demonstrates the "
        "adapters run end to end and records real latency/memory on this machine; it is not "
        "a transcription/interpretation quality benchmark against real personal recordings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
