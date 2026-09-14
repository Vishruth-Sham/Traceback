#!/usr/bin/env python3
"""Reproducible latency/memory benchmark for the installed local models.

Measures the installed whisper.cpp Whisper `small` and Ollama `qwen3.5:4b`
runtimes on THIS machine, over several iterations, using the same synthetic
speech (macOS `say` + `afconvert`, no microphone) and one fixed typed-text
fixture that `scripts/model_smoke.py` uses for its single-shot smoke check.
This script adds repeated iterations and min/mean/max/cold-vs-warm
statistics; it downloads nothing and exits early with a precise reason if a
runtime/model/synthesis tool is missing, rather than trying to install one.

This is a latency/memory benchmark, not a transcription/interpretation
quality benchmark: it does not evaluate accuracy against real personal
recordings (explicitly out of scope; see docs/local-models.md), and the
default fixtures are short, fixed, non-personal sentences.
"""
import argparse
import json
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.config import get_settings

SYNTHETIC_UTTERANCE = "Buy milk tomorrow and finish the capture endpoint by five p m for Traceback"
SYNTHETIC_TEXT_CAPTURE = "Note to self: read the second chapter of the book on distributed systems this weekend."


def _whisper_available(settings) -> str | None:
    if not (shutil.which("whisper-cli") or settings.whisper_binary.is_file()):
        return "whisper-cli binary not found on PATH"
    if not settings.whisper_model_path.is_file():
        return f"whisper model weights not found at {settings.whisper_model_path}"
    if not (shutil.which("say") and shutil.which("afconvert")):
        return "macOS `say`/`afconvert` not available to synthesize a speech fixture"
    return None


def _ollama_available(settings) -> str | None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=3) as response:
            tags = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"could not reach Ollama at {settings.ollama_base_url}: {exc}"
    if not any(m.get("name") == settings.ollama_model for m in tags.get("models", [])):
        return f"model {settings.ollama_model} is not pulled in this Ollama instance"
    return None


def _synthesize_audio(tmp_dir: Path) -> Path:
    aiff_path = tmp_dir / "benchmark.aiff"
    wav_path = tmp_dir / "benchmark.wav"
    subprocess.run(["say", "-o", str(aiff_path), SYNTHETIC_UTTERANCE], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff_path), str(wav_path)], check=True)
    return wav_path


def _stats(latencies: list[float]) -> dict:
    return {
        "iterations": len(latencies),
        "latencies_s": [round(v, 3) for v in latencies],
        "min_s": round(min(latencies), 3),
        "mean_s": round(statistics.mean(latencies), 3),
        "max_s": round(max(latencies), 3),
        "cold_first_call_s": round(latencies[0], 3),
        "warm_mean_s_excl_first": round(statistics.mean(latencies[1:]), 3) if len(latencies) > 1 else None,
    }


def benchmark_whisper(settings, iterations: int) -> dict:
    from processor.transcription import transcribe

    with tempfile.TemporaryDirectory(prefix="traceback-benchmark-") as tmp:
        wav_path = _synthesize_audio(Path(tmp))
        latencies = []
        transcript = None
        for _ in range(iterations):
            start = time.perf_counter()
            transcript = transcribe(wav_path, settings=settings)
            latencies.append(time.perf_counter() - start)
    result = _stats(latencies)
    # A high-water mark across all reaped children in this process; this
    # script reaps only whisper-cli children before this point.
    result["child_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    result["last_transcript"] = transcript
    result["input_utterance"] = SYNTHETIC_UTTERANCE
    return result


def benchmark_ollama(settings, iterations: int) -> dict:
    from processor.interpretation import interpret

    category_id = str(uuid.uuid4())
    context = {
        "captured_at": "2026-09-14T09:00:00+05:30",
        "source_timezone": "Asia/Kolkata",
        "source_date": "2026-09-14",
        "categories": [{"id": category_id, "slug": "projects", "name": "Projects"}],
    }
    latencies = []
    proposal = None
    for _ in range(iterations):
        start = time.perf_counter()
        proposal = interpret(SYNTHETIC_TEXT_CAPTURE, context, settings=settings)
        latencies.append(time.perf_counter() - start)
    result = _stats(latencies)
    result["last_proposal"] = proposal
    result["input_text"] = SYNTHETIC_TEXT_CAPTURE
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=30)
    result["ollama_ps"] = ps.stdout.strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--whisper-iterations", type=int, default=5, help="transcription calls to time (default: 5)")
    parser.add_argument("--ollama-iterations", type=int, default=5, help="interpretation calls to time (default: 5)")
    parser.add_argument("--skip-whisper", action="store_true")
    parser.add_argument("--skip-ollama", action="store_true")
    parser.add_argument("--output-json", type=Path, default=None, help="also write the full report to this path")
    args = parser.parse_args()

    settings = get_settings()
    report: dict = {
        "machine_note": "Measured on whatever machine ran this script; re-run locally to reproduce, do not assume these numbers transfer to another machine.",
        "whisper_model_path": str(settings.whisper_model_path),
        "ollama_model": settings.ollama_model,
    }
    exit_code = 0

    if args.skip_whisper:
        report["whisper"] = {"skipped": "--skip-whisper"}
    else:
        problem = _whisper_available(settings)
        if problem:
            report["whisper"] = {"measured": False, "reason": problem}
            print(f"[whisper] not measured: {problem}")
        else:
            print(f"[whisper] running {args.whisper_iterations} transcription iterations...")
            report["whisper"] = {"measured": True, **benchmark_whisper(settings, args.whisper_iterations)}
            w = report["whisper"]
            print(f"[whisper] cold={w['cold_first_call_s']}s warm_mean={w['warm_mean_s_excl_first']}s peak_rss_mb={w['child_peak_rss_bytes'] / 1024 / 1024:.0f}")

    if args.skip_ollama:
        report["ollama"] = {"skipped": "--skip-ollama"}
    else:
        problem = _ollama_available(settings)
        if problem:
            report["ollama"] = {"measured": False, "reason": problem}
            print(f"[ollama] not measured: {problem}")
        else:
            print(f"[ollama] running {args.ollama_iterations} interpretation iterations...")
            report["ollama"] = {"measured": True, **benchmark_ollama(settings, args.ollama_iterations)}
            o = report["ollama"]
            print(f"[ollama] cold={o['cold_first_call_s']}s warm_mean={o['warm_mean_s_excl_first']}s")

    print("\n--- Full report (JSON) ---")
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.output_json:
        args.output_json.write_text(text)
        print(f"\nWrote {args.output_json}")

    print(
        "\nThis measures latency/memory of the installed runtimes on this machine using "
        "short synthetic/fixed fixtures. It is not a transcription/interpretation quality "
        "benchmark against real personal recordings; no such benchmark exists here."
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
