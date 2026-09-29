"""Deterministic intent lexicon (§8.5). The model's intent is a suggestion; this decides."""
import re
from typing import Any

from backend.voice_policy.text import normalize

ACTION_VERBS = {
    "call", "email", "text", "message", "submit", "send", "buy", "pay", "book", "finish", "schedule", "renew", "order",
    "cancel", "return", "clean", "fix", "write", "prepare", "review", "check", "follow", "ask", "tell", "pack", "plan",
    "pick", "drop", "print", "sign", "file", "confirm", "reply", "update", "upload", "download", "read", "watch",
}
_DETERMINER = r"(?:a\s+|an\s+|the\s+|my\s+)?(?:new\s+)?"
_TASK_ADD = re.compile(rf"\b(?:add|create|make|put|new)\s+{_DETERMINER}(?:task|todo|to do)\b")
_NOTE_ADD = re.compile(rf"\b(?:add|create|make|save|start)\s+{_DETERMINER}note\b")
_REMIND = re.compile(r"\bremind me\b")
_TODO_LEAD = re.compile(r"^(?:please\s+)?(?:to do|todo)\b")
_NOTE_LEAD = re.compile(r"^(?:please\s+)?(?:note\b|remember that\b)")
_DELETE = re.compile(r"\b(?:delete|erase|trash|wipe|remove|destroy)\b")
_DELETE_TARGET = re.compile(r"\b(?:notes?|tasks?|items?|everything|all|folders?|projects?|captures?|recordings?|memory|memories|data)\b")
_ORGANIZE = re.compile(r"^(?:please\s+)?(?:move|archive|reopen)\b|\bmark\b.*\b(?:done|complete|completed|finished)\b")
_ADD_LEAD = re.compile(r"^(?:please\s+)?(?:add|put|save)\s+(?P<rest>.+)$")
_SELF_CORRECTION = re.compile(r"\b(?:no wait|scratch that|never mind|i mean|actually no|sorry i meant)\b")
_SECOND_COMMAND = re.compile(r"\b(?:and then|and also|also)\s+(?:remind me|add (?:a )?(?:task|note)|create (?:a )?(?:task|note))\b")

ORGANIZATION_INTENTS = {"move_item", "complete_task", "reopen_task", "archive_item"}


def deterministic_flags(transcript: str) -> set[str]:
    text = normalize(transcript)
    flags: set[str] = set()
    if _SELF_CORRECTION.search(text):
        flags.add("self_correction")
    if _SECOND_COMMAND.search(text) or len(_REMIND.findall(text)) > 1 or len(_TASK_ADD.findall(text)) + len(_NOTE_ADD.findall(text)) > 1:
        flags.add("multi_intent")
    if _DELETE.search(text) and _DELETE_TARGET.search(text) and not _NOTE_ADD.search(text) and not _TASK_ADD.search(text):
        flags.add("requested_delete")
    if _ORGANIZE.search(text):
        flags.add("organization_request")
    return flags


def derive_intent(transcript: str, *, has_deadline: bool) -> dict[str, Any]:
    """Return {intent, basis, explicit, alternative, conflict}; intent is None when no rule applies."""
    text = normalize(transcript)
    note_explicit = bool(_NOTE_ADD.search(text) or _NOTE_LEAD.search(text))
    task_add = bool(_TASK_ADD.search(text) or _TODO_LEAD.search(text))
    remind = bool(_REMIND.search(text))
    task_explicit = task_add or remind
    if note_explicit and task_explicit:
        if _NOTE_ADD.search(text) and not task_add:
            # "add a note to remind me to ...": the noun that is the object of add wins.
            return {"intent": "create_note", "basis": "explicit_note_word", "explicit": True, "alternative": "create_task", "conflict": True}
        if task_add and not _NOTE_ADD.search(text):
            return {"intent": "create_task", "basis": "explicit_task_word", "explicit": True, "alternative": "create_note", "conflict": True}
        return {"intent": None, "basis": "conflicting_explicit", "explicit": False, "alternative": None, "conflict": True}
    if note_explicit:
        return {"intent": "create_note", "basis": "explicit_note_word", "explicit": True, "alternative": None, "conflict": False}
    if task_add:
        return {"intent": "create_task", "basis": "explicit_task_word", "explicit": True, "alternative": None, "conflict": False}
    if remind:
        return {"intent": "create_task", "basis": "explicit_reminder_verb", "explicit": True, "alternative": None, "conflict": False}
    lead = _ADD_LEAD.match(text)
    body = lead.group("rest") if lead else text
    first = body.split()[0] if body.split() else ""
    if first in ACTION_VERBS and (has_deadline or lead):
        return {"intent": "create_task", "basis": "inferred_deadline_verb" if has_deadline else "inferred_add_verb", "explicit": False, "alternative": None, "conflict": False}
    if lead and not has_deadline:
        return {"intent": "create_note", "basis": "inferred_add_noun", "explicit": False, "alternative": None, "conflict": False}
    return {"intent": None, "basis": None, "explicit": False, "alternative": None, "conflict": False}


_TASK_PREFIX = re.compile(
    r"^(?:please\s+)?(?:(?:remind me\s+(?:to|that|about)|add\s+(?:a\s+|an\s+)?(?:new\s+)?(?:task|to-?do|todo)(?:\s+(?:to|called|named|for))?|"
    r"create\s+(?:a\s+|an\s+)?(?:new\s+)?(?:task|to-?do|todo)(?:\s+(?:to|called|named|for))?|to-?do:?|add)\s+)",
    re.IGNORECASE,
)
_NOTE_CALLED = re.compile(r"\b(?:called|named|titled)\s+(?P<title>.+)$", re.IGNORECASE)
_NOTE_PREFIX = re.compile(r"^(?:please\s+)?(?:(?:add|create|make|save)\s+(?:a\s+|an\s+)?(?:new\s+)?note(?:\s+(?:that|about|on))?|note\s*:?|remember that)\s*", re.IGNORECASE)


def strip_span(text: str, phrase: str | None) -> str:
    if not phrase:
        return text
    pattern = re.compile(r"\s*(?:\b(?:by|on|at|for|before|due|until)\s+)?" + re.escape(phrase.strip()) + r"\b[\s,.]*", re.IGNORECASE)
    return pattern.sub(" ", text, count=1).strip()


def strip_destination_tail(text: str, destination_phrase: str | None) -> str:
    if not destination_phrase:
        return text
    pattern = re.compile(
        r"\s+(?:in|into|to|under|inside|within)\s+(?:the\s+|my\s+)?(?:(?:project|folder|category)\s+)?" + re.escape(destination_phrase.strip()) + r"[\s.]*$",
        re.IGNORECASE,
    )
    return pattern.sub("", text).strip()


def derive_task_title(transcript: str, *, date_phrase: str | None, time_phrase: str | None, destination_phrase: str | None) -> str:
    text = transcript.strip()
    text = strip_destination_tail(text, destination_phrase)
    for phrase in (time_phrase, date_phrase):
        text = strip_span(text, phrase)
    text = _TASK_PREFIX.sub("", text, count=1).strip(" ,.;:")
    return text[:1].upper() + text[1:] if text else ""


def derive_note_title(transcript: str, *, destination_phrase: str | None) -> tuple[str, bool]:
    """Return (title, derived). `derived` is False only for an explicit "called X"."""
    text = strip_destination_tail(transcript.strip(), destination_phrase)
    called = _NOTE_CALLED.search(text)
    if called:
        return called.group("title").strip(" ,.;:"), False
    body = _NOTE_PREFIX.sub("", text, count=1).strip(" ,.;:")
    if not body:
        body = text
    words = body.split()[:8]
    title = " ".join(words).strip(" ,.;:")
    return title[:1].upper() + title[1:] if title else "", True
