#!/usr/bin/env python3
"""Idempotent local setup/check for the processor's model dependencies.

Installs nothing without explicit `--install`; by default it only reports
what is present and what would need to be downloaded, with disk-use
estimates, per the contract's requirement to document download size before
initiating large downloads. Model weights are stored outside the repository
(Homebrew cellar + `~/.cache/whisper-cpp`, Ollama's own model store) and are
never written into Git.
"""

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.config import get_settings

WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
WHISPER_MODEL_APPROX_BYTES = 488 * 1024 * 1024  # ggml-small.bin is ~488MB
OLLAMA_MODEL_APPROX_BYTES = int(3.4 * 1024 * 1024 * 1024)  # qwen3.5:4b Q4_K_M is ~3.4GB


def check_whisper_binary() -> bool:
    settings = get_settings()
    found = settings.whisper_binary.is_file() or shutil.which(str(settings.whisper_binary))
    print(f"[whisper-cli] {'found: ' + str(found) if found else 'MISSING'}")
    if not found:
        print("  install with: brew install whisper-cpp")
    return bool(found)


def check_whisper_model(install: bool) -> bool:
    settings = get_settings()
    path = settings.whisper_model_path
    if path.is_file():
        print(f"[whisper model] found: {path} ({path.stat().st_size / 1024 / 1024:.0f} MB)")
        return True
    print(f"[whisper model] MISSING at {path}")
    print(f"  download is ~{WHISPER_MODEL_APPROX_BYTES / 1024 / 1024:.0f} MB from {WHISPER_MODEL_URL}")
    if not install:
        print("  re-run with --install to download it")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    print("  downloading...")
    urllib.request.urlretrieve(WHISPER_MODEL_URL, path)
    print(f"  saved to {path} ({path.stat().st_size / 1024 / 1024:.0f} MB)")
    return True


def check_ollama(install: bool) -> bool:
    settings = get_settings()
    ollama_binary = shutil.which("ollama")
    if not ollama_binary:
        print("[ollama] MISSING binary (install from https://ollama.com/download)")
        return False
    print(f"[ollama] found: {ollama_binary}")
    listed = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
    if settings.ollama_model in listed.stdout:
        print(f"[ollama model] found: {settings.ollama_model}")
        return True
    print(f"[ollama model] MISSING: {settings.ollama_model}")
    print(f"  download is ~{OLLAMA_MODEL_APPROX_BYTES / 1024 / 1024 / 1024:.1f} GB (Q4_K_M)")
    if not install:
        print("  re-run with --install to pull it")
        return False
    print("  pulling...")
    subprocess.run(["ollama", "pull", settings.ollama_model], check=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="download missing weights/models")
    args = parser.parse_args()

    ok = True
    ok &= check_whisper_binary()
    ok &= check_whisper_model(args.install)
    ok &= check_ollama(args.install)

    if ok:
        print("\nAll local model dependencies are present.")
    else:
        print("\nSome dependencies are missing; see messages above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
