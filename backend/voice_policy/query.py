"""Deterministic read-only query lexicon. Pure text -> intent, no I/O.

Mirrors `voice_policy.intent`'s "the model's word is a suggestion, this decides" stance,
but for P0 read-only commands: query classification never touches the model, so there is
no hallucination risk and no ambiguity-guessing risk on the classification step itself.
"""
import re
from dataclasses import dataclass
from typing import Literal

from backend.voice_policy.text import normalize

QueryKind = Literal["all_tasks", "overdue_tasks", "inbox_summary", "search", "navigate", "followup_select", "not_a_query"]

_OVERDUE = re.compile(r"\b(?:overdue|past due|behind schedule)\b")
_LATE_TASKS = re.compile(r"\blate\b.*\btasks?\b|\btasks?\b.*\blate\b")
_ALL_TASKS = re.compile(
    r"^(?:please\s+)?(?:what(?:'s|\s+is|\s+are)\s+(?:on\s+)?my\s+(?:task\s+list|tasks)|"
    r"show(?:\s+me)?\s+(?:all\s+)?(?:my\s+)?tasks|(?:my\s+)?task\s+list)[\s.?!]*$"
)
_INBOX = re.compile(r"\binbox\b")
_CREATE_HINT = re.compile(r"\b(?:add|create|make|remind me|new (?:task|note))\b")

_NAVIGATE = re.compile(
    r"^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:open|go to|navigate to|take me to|switch to)\s+(?P<phrase>.+?)[\s.?!]*$"
)
_SEARCH = re.compile(
    r"^(?:please\s+)?(?:find|search(?:\s+for)?|look for|show me)\s+(?P<phrase>.+?)[\s.?!]*$"
)

_LEADING_FILLER = re.compile(r"^(?:the\s+|my\s+|a\s+|an\s+)+")
_LEADING_NOUN = re.compile(r"^(?:project|folder|note|notes?|task|tasks?|item|items?)\s+(?:called\s+|named\s+|about\s+|on\s+|for\s+)?")
_TRAILING_NOUN = re.compile(r"\s+(?:project|folder)$")

_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_ORDINAL_WORD = re.compile(
    r"^(?:open\s+|select\s+|pick\s+|number\s+|option\s+)?(?:the\s+)?(?P<word>" + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True)) + r")\s*(?:one|option|result)?$"
)
_ORDINAL_NUMBER = re.compile(r"^(?:open\s+|select\s+|pick\s+|number\s+|option\s+)*#?(?P<num>\d{1,2})(?:st|nd|rd|th)?$")


@dataclass(frozen=True)
class QueryClassification:
    kind: QueryKind
    phrase: str | None = None
    index: int | None = None


def _clean_phrase(phrase: str) -> str:
    phrase = _LEADING_FILLER.sub("", phrase.strip())
    phrase = _LEADING_NOUN.sub("", phrase)
    phrase = _LEADING_FILLER.sub("", phrase)
    phrase = _TRAILING_NOUN.sub("", phrase)
    return phrase.strip(" ,.;:")


def clean_query_phrase(phrase: str | None) -> str:
    """Normalize a model-supplied phrase the same way a regex-captured one is cleaned."""
    return _clean_phrase(normalize(phrase))


def classify_query(transcript: str, *, has_followup_context: bool) -> QueryClassification:
    """Classify one transcript. `has_followup_context` gates ordinal-only utterances:
    a bare "the first one" only means something when a prior ambiguity/result list is
    still on screen; otherwise it is not a recognizable command at all.
    """
    text = normalize(transcript)
    if not text:
        return QueryClassification(kind="not_a_query")

    if has_followup_context:
        word_match = _ORDINAL_WORD.match(text)
        if word_match:
            return QueryClassification(kind="followup_select", index=_ORDINAL_WORDS[word_match.group("word")])
        number_match = _ORDINAL_NUMBER.match(text)
        if number_match:
            index = int(number_match.group("num"))
            if 1 <= index <= 20:
                return QueryClassification(kind="followup_select", index=index)

    if _CREATE_HINT.search(text):
        return QueryClassification(kind="not_a_query")

    if _OVERDUE.search(text) or _LATE_TASKS.search(text):
        return QueryClassification(kind="overdue_tasks")

    if _ALL_TASKS.match(text):
        return QueryClassification(kind="all_tasks")

    if _INBOX.search(text):
        return QueryClassification(kind="inbox_summary")

    navigate_match = _NAVIGATE.match(text)
    if navigate_match:
        phrase = _clean_phrase(navigate_match.group("phrase"))
        if phrase:
            return QueryClassification(kind="navigate", phrase=phrase)

    search_match = _SEARCH.match(text)
    if search_match:
        phrase = _clean_phrase(search_match.group("phrase"))
        if phrase:
            return QueryClassification(kind="search", phrase=phrase)

    return QueryClassification(kind="not_a_query")
