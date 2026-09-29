"""Deterministic spoken destination -> canonical catalog ID resolution (§8.4)."""
import re
from typing import Any

from backend.voice_policy.text import normalize, spoken_path

_QUALIFIER = re.compile(r"^(?:(?:in|into|to|under|inside|within)\s+)?(?:(?:the|my)\s+)?(?:(project|folder|category)\s+)?(?:(?:the|my)\s+)?(.+)$")
# Spoken variants of the six fixed categories, in normalized form.
_ALIASES = {
    "health food": "health and food",
    "food and health": "health and food",
    "health and nutrition": "health and food",
}


def split_qualifier(phrase: str) -> tuple[str | None, str]:
    """Return (kind_hint, cleaned phrase) after removing a leading "in project"-style qualifier."""
    value = spoken_path(phrase)
    match = _QUALIFIER.match(value)
    if not match:
        return None, value
    return match.group(1), match.group(2).strip()


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split("/") if part.strip()]


def _distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for index in range(len(long_)):
        if long_[:index] + long_[index + 1 :] == short:
            return True
    return False


def _fuzzy_equal(phrase: str, title: str) -> bool:
    left, right = phrase.split(), title.split()
    if len(left) != len(right) or phrase == title:
        return False
    for a, b in zip(left, right):
        if a == b:
            continue
        if len(a) < 5 or len(b) < 5 or not _distance_at_most_one(a, b):
            return False
    return True


def _candidate(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: entry.get(key) for key in ("kind", "id", "title", "path", "version")}


def resolve_destination(phrase: str | None, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve a spoken phrase over the live catalog.

    status: none | resolved | ambiguous | not_found. `chosen` is set only for
    `resolved`; `confidence` is one of high/medium/low (low is always reviewed).
    """
    if not phrase or not normalize(phrase):
        return {"status": "none", "phrase": None, "source": None, "candidates": [], "chosen": None, "confidence": None}
    kind_hint, cleaned = split_qualifier(phrase)
    entries = [entry for entry in catalog if kind_hint is None or entry["kind"] == kind_hint]
    normalized = [(entry, spoken_path(entry["path"]), normalize(entry["title"])) for entry in entries]
    parts = _parts(cleaned)
    base = {"phrase": phrase, "source": "spoken", "chosen": None, "confidence": None}

    def done(matches: list[dict[str, Any]], confidence: str) -> dict[str, Any]:
        if len(matches) == 1:
            return {**base, "status": "resolved", "candidates": [_candidate(matches[0])], "chosen": _candidate(matches[0]), "confidence": confidence}
        return {**base, "status": "ambiguous", "candidates": [_candidate(entry) for entry in matches]}

    if not parts:
        return {**base, "status": "not_found", "candidates": []}

    joined = " / ".join(parts)
    matches = [entry for entry, path, _title in normalized if path == joined]
    if matches:
        return done(matches, "high")

    alias = _ALIASES.get(parts[0], parts[0])
    if len(parts) > 1:
        category_paths = {spoken_path(entry["path"]).split(" / ")[0] for entry, _path, _title in normalized}
        first = alias if alias in category_paths else parts[0]
        if first in category_paths:
            middle = parts[1:-1]
            matches = []
            for entry, path, _title in normalized:
                entry_parts = path.split(" / ")
                if entry_parts[0] == first and entry_parts[-1] == parts[-1] and entry_parts[1:-1] == middle:
                    matches.append(entry)
            if matches:
                return done(matches, "high")
    elif alias != parts[0]:
        matches = [entry for entry, path, _title in normalized if entry["kind"] == "category" and path == alias]
        if matches:
            return done(matches, "high")

    leaf = parts[-1]
    matches = [entry for entry, _path, title in normalized if title == leaf]
    if matches:
        return done(matches, "medium")

    matches = [entry for entry, _path, title in normalized if _fuzzy_equal(leaf, title)]
    if matches:
        return done(matches, "low")
    return {**base, "status": "not_found", "candidates": []}
