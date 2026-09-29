"""Normalization and grounding of model-suggested spans against the transcript."""
import re
import unicodedata

_KEEP = re.compile(r"[^a-z0-9/:\-\s]")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("&", " and ").replace("'", "")
    # A hyphen between digits is part of a date ("2026-03-08", "5-10"); elsewhere it separates words.
    value = re.sub(r"(?<!\d)-|-(?!\d)", " ", value)
    value = _KEEP.sub("", value)
    # Spoken separators become the path separator used by the destination resolver.
    value = re.sub(r"\s*/\s*", " / ", value)
    return re.sub(r"\s+", " ", value).strip()


def spoken_path(text: str | None) -> str:
    """Normalize and turn spoken "slash"/"then" into the path separator."""
    value = normalize(text)
    value = re.sub(r"\b(slash|then)\b", "/", value)
    return re.sub(r"\s*/\s*", " / ", re.sub(r"\s+", " ", value)).strip()


def is_grounded(span: str | None, transcript: str) -> bool:
    """True only when the normalized span occurs, on word boundaries, in the transcript."""
    needle = normalize(span)
    if not needle:
        return False
    haystack = f" {normalize(transcript)} "
    return f" {needle} " in haystack or f" {spoken_path(span)} " in f" {spoken_path(transcript)} "
