"""Check that the app, Python package, and lockfiles share one release version."""

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def read_toml(path: str) -> dict:
    return tomllib.loads((ROOT / path).read_text())


versions = {
    "pyproject.toml": read_toml("pyproject.toml")["project"]["version"],
    "frontend/package.json": read_json("frontend/package.json")["version"],
    "frontend/package-lock.json (root)": read_json("frontend/package-lock.json")["version"],
    "frontend/package-lock.json": read_json("frontend/package-lock.json")["packages"][""]["version"],
    "uv.lock": next(package["version"] for package in read_toml("uv.lock")["package"] if package["name"] == "traceback-local"),
}

if len(set(versions.values())) != 1:
    raise SystemExit(f"Version mismatch: {versions}")

print(f"Traceback v{next(iter(versions.values()))}")
