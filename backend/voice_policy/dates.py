"""Deterministic English date/time parsing over verbatim spoken spans (§8.3).

The model supplies phrases only; every calendar value comes from here. All
weekday logic follows the reviewed tables: weeks are Monday-Sunday, "next X"
is the X of the next Monday-start week, a bare weekday equal to today's is
ambiguous, and month/day without a year resolves to the nearest date on or
after the anchor day. No result is ever a planned date; there is no Today view.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.voice_policy.text import normalize

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAY_ALIASES = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_MONTH_ALIASES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "a": 1, "an": 1}
_TENS = {"twenty": 20, "thirty": 30}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
             "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
             "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
DATE_ASSUMED_YEAR_DAYS = 90


@dataclass
class DeadlineResult:
    due_date: date | None = None
    due_time: time | None = None
    due_timezone: str | None = None
    basis: str | None = None
    warnings: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    relative: bool = False

    def as_dict(self) -> dict:
        return {
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "due_time": self.due_time.isoformat() if self.due_time else None,
            "due_timezone": self.due_timezone,
        }


def _number_words(tokens: list[str]) -> tuple[int, int] | None:
    """Parse a leading cardinal/ordinal number word or digits; return (value, tokens consumed)."""
    if not tokens:
        return None
    head = tokens[0]
    match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?", head)
    if match:
        return int(match.group(1)), 1
    if head in _ORDINALS:
        return _ORDINALS[head], 1
    if head in _TENS:
        tail = tokens[1] if len(tokens) > 1 else ""
        if tail in _UNITS and _UNITS[tail] < 10:
            return _TENS[head] + _UNITS[tail], 2
        if tail in _ORDINALS and _ORDINALS[tail] < 10:
            return _TENS[head] + _ORDINALS[tail], 2
        return _TENS[head], 1
    if head in _UNITS:
        return _UNITS[head], 1
    return None


def time_exists(day: date, wall: time, zone: str) -> bool:
    tz = ZoneInfo(zone)
    local = datetime.combine(day, wall)
    return any(
        local.replace(tzinfo=tz, fold=fold).astimezone(ZoneInfo("UTC")).astimezone(tz).replace(tzinfo=None) == local for fold in (0, 1)
    )


_TIME_RE = re.compile(r"\b(?P<at>at\s+)?(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<meridiem>a\s?m|p\s?m|oclock)?\b(?!\s*(?:st|nd|rd|th|/|-))")
_WORD_TIME_RE = re.compile(r"\b(?P<at>at\s+)?(?P<word>" + "|".join(w for w in _UNITS if w not in ("a", "an")) + r")\s*(?P<meridiem>a\s?m|p\s?m)\b")


def _extract_time(text: str) -> tuple[time | None, list[str], str]:
    """Return (local wall time, warnings, remaining text)."""
    warnings: list[str] = []
    match = re.search(r"\b(?:at\s+)?(noon|midday)\b", text)
    if match:
        return time(12, 0), warnings, text.replace(match.group(0), " ")
    match = re.search(r"\b(?:at\s+)?midnight\b", text)
    if match:
        return time(0, 0), ["time_midnight_ambiguous"], text.replace(match.group(0), " ")
    match = _WORD_TIME_RE.search(text)
    if match:
        found = _combine(_UNITS[match.group("word")], 0, match.group("meridiem").replace(" ", ""), warnings)
        return found, warnings, (text[: match.start()] + " " + text[match.end() :]).strip()
    for match in _TIME_RE.finditer(text):
        meridiem = (match.group("meridiem") or "").replace(" ", "")
        if meridiem == "oclock":
            meridiem = ""
        has_minute = match.group("minute") is not None
        # A bare number with no "at", meridiem, or minutes is a date part, not a clock time.
        if not (meridiem or has_minute or match.group("at") or match.group("meridiem")):
            continue
        hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
        remaining = (text[: match.start()] + " " + text[match.end() :]).strip()
        if not meridiem and has_minute and (hour >= 13 or hour == 0):
            return time(hour, minute), warnings, remaining
        return _combine(hour, minute, meridiem, warnings), warnings, remaining
    return None, warnings, text


def _combine(hour: int, minute: int, meridiem: str, warnings: list[str]) -> time | None:
    if minute > 59 or hour > 23:
        warnings.append("time_unresolved")
        return None
    if meridiem in ("am", "pm"):
        if hour < 1 or hour > 12:
            warnings.append("time_unresolved")
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
        return time(hour, minute)
    if hour > 12:
        return time(hour, minute)
    warnings.append("meridiem_assumed")
    # Heuristic shown to the user: 1-7 -> pm, 8-11 -> am, 12 -> pm.
    hour = hour + 12 if 1 <= hour <= 7 else (12 if hour == 12 else hour)
    return time(hour, minute)


def _month_day(text: str, anchor: date) -> tuple[date, list[str]] | None:
    tokens = text.replace(",", " ").split()
    month = None
    day = None
    year = None
    for index, token in enumerate(tokens):
        month_number = MONTHS.index(token) + 1 if token in MONTHS else _MONTH_ALIASES.get(token)
        if month_number is None:
            continue
        month = month_number
        before = tokens[:index]
        if before and before[-1] == "of":
            before = before[:-1]
        after = tokens[index + 1 :]
        parsed = _number_words(after)
        if parsed:
            day, used = parsed
            rest = after[used:]
        else:
            parsed = _number_words(before[-2:]) if len(before) >= 2 and before[-2] in _TENS else _number_words(before[-1:])
            if not parsed:
                return None
            day, used = parsed
            rest = after
        if rest and re.fullmatch(r"\d{4}", rest[0]):
            year = int(rest[0])
        elif rest and re.fullmatch(r"\d{2}", rest[0]):
            year = 2000 + int(rest[0])
            return _finish_month_day(anchor, month, day, year, ["year_two_digit"])
        break
    if month is None or day is None:
        return None
    return _finish_month_day(anchor, month, day, year, [])


def _finish_month_day(anchor: date, month: int, day: int, year: int | None, warnings: list[str]):
    if year is not None:
        try:
            return date(year, month, day), warnings
        except ValueError:
            return None
    for offset in range(0, 9):
        try:
            candidate = date(anchor.year + offset, month, day)
        except ValueError:
            continue
        if candidate >= anchor:
            if (candidate - anchor).days > DATE_ASSUMED_YEAR_DAYS:
                warnings = [*warnings, "year_assumed"]
            return candidate, warnings
    return None


def _numeric_date(text: str, anchor: date):
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if match:
        try:
            return "iso", [date(int(match.group(1)), int(match.group(2)), int(match.group(3)))], []
        except ValueError:
            return "iso", [], []
    match = re.search(r"\b(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{2,4}))?\b", text.replace(" / ", "/"))
    if not match:
        return None
    a, b = int(match.group(1)), int(match.group(2))
    raw_year = match.group(3)
    warnings = ["date_numeric_format"]
    year = None
    if raw_year:
        year = int(raw_year) if len(raw_year) == 4 else 2000 + int(raw_year)
        if len(raw_year) != 4:
            warnings.append("year_two_digit")
    readings: list[date] = []
    for month, day in ((a, b), (b, a)):
        if not (1 <= month <= 12):
            continue
        result = _finish_month_day(anchor, month, day, year, [])
        if result and result[0] not in readings:
            readings.append(result[0])
    return "numeric", readings, warnings


def _weekday_index(token: str) -> int | None:
    if token in WEEKDAYS:
        return WEEKDAYS.index(token)
    return _WEEKDAY_ALIASES.get(token)


def _resolve(text: str, anchor: datetime, wall: time | None, result: DeadlineResult) -> bool:
    """Populate result.due_date from `text` relative to anchor. Returns False if unresolvable."""
    today = anchor.date()
    tokens = text.split()
    clock = anchor.time().replace(tzinfo=None)

    if not tokens:
        if wall is None:
            return False
        result.relative = True
        if wall > clock:
            result.due_date, result.basis = today, "time_only_today"
        else:
            result.due_date, result.basis = today + timedelta(days=1), "time_only_rolled"
            result.warnings.append("date_assumed")
        return True

    numeric = _numeric_date(text, today)
    if numeric:
        kind, readings, warnings = numeric
        result.warnings.extend(warnings)
        if kind == "iso":
            if not readings:
                return False
            result.due_date, result.basis = readings[0], "iso_date"
            return True
        if not readings:
            return False
        result.basis = "numeric_date"
        result.relative = True
        if len(readings) == 1:
            result.due_date = readings[0]
        else:
            result.warnings.append("date_numeric_ambiguous")
            result.alternatives.extend({"due_date": reading.isoformat(), "due_time": wall.isoformat() if wall else None} for reading in readings)
        return True

    month_day = _month_day(text, today)
    if month_day:
        result.due_date, extra = month_day
        result.warnings.extend(extra)
        has_year = bool(re.search(r"\b\d{4}\b", text)) or "year_two_digit" in extra
        result.basis = "month_day_explicit_year" if has_year else "month_day_nearest"
        result.relative = not has_year
        return True

    if "day after tomorrow" in text:
        result.due_date, result.basis, result.relative = today + timedelta(days=2), "offset_days", True
        return True
    if "yesterday" in tokens:
        result.due_date, result.basis, result.relative = today - timedelta(days=1), "yesterday", True
        result.warnings.append("deadline_past")
        return True
    if "tomorrow" in tokens:
        result.due_date, result.basis, result.relative = today + timedelta(days=1), "tomorrow", True
        return True
    if any(token in ("today", "tonight") for token in tokens) or "this evening" in text or "this morning" in text or "this afternoon" in text:
        result.due_date, result.basis, result.relative = today, "today", True
        if wall is not None and wall <= clock:
            result.warnings.append("time_passed_today")
        return True

    match = re.search(r"\bin\s+(.+?)\s+(day|days|week|weeks)\b", text)
    if match:
        parsed = _number_words(match.group(1).split())
        if parsed and parsed[1] == len(match.group(1).split()):
            days = parsed[0] * (7 if match.group(2).startswith("week") else 1)
            result.due_date, result.basis, result.relative = today + timedelta(days=days), "offset_days", True
            return True
        return False

    modifier = None
    target = None
    for index, token in enumerate(tokens):
        weekday = _weekday_index(token)
        if weekday is not None:
            target = weekday
            if index and tokens[index - 1] in ("this", "next", "last", "coming", "upcoming"):
                modifier = tokens[index - 1]
            break
    if target is None:
        return False
    result.relative = True
    weekday_today = today.weekday()
    upcoming = today + timedelta(days=(target - weekday_today) % 7 or 7)
    if modifier == "next":
        monday_next = today + timedelta(days=7 - weekday_today)
        default = monday_next + timedelta(days=target)
        alternate = upcoming if upcoming != default else default + timedelta(days=7)
        result.due_date, result.basis = default, "next_calendar_week_weekday"
        result.warnings.append("date_ambiguous_next_weekday")
        result.alternatives.append({"due_date": alternate.isoformat(), "due_time": wall.isoformat() if wall else None})
        return True
    if modifier == "last":
        back = (weekday_today - target) % 7 or 7
        result.due_date, result.basis = today - timedelta(days=back), "last_weekday"
        result.warnings.append("deadline_past")
        return True
    if target != weekday_today:
        result.due_date, result.basis = upcoming, "next_occurrence_weekday"
        return True
    plus_week = today + timedelta(days=7)
    if modifier == "this":
        if wall is not None and wall <= clock:
            result.due_date, result.basis = plus_week, "this_weekday_time_passed"
            result.warnings.append("time_passed_today")
        else:
            result.due_date, result.basis = today, "this_weekday_today"
        return True
    ahead = wall is not None and wall > clock
    default, other = (today, plus_week) if ahead else (plus_week, today)
    result.due_date, result.basis = default, "same_weekday_ambiguous"
    result.warnings.append("date_ambiguous_same_weekday")
    result.alternatives.append({"due_date": other.isoformat(), "due_time": wall.isoformat() if wall else None})
    return True


def _parse_at(text: str, wall: time | None, anchor: datetime) -> DeadlineResult:
    result = DeadlineResult()
    if not _resolve(text, anchor, wall, result) and text.strip():
        result.warnings.append("date_unresolved")
    return result


def parse_deadline(
    date_phrase: str | None,
    time_phrase: str | None,
    *,
    anchor: datetime,
    timezone: str,
    receipt: datetime | None = None,
) -> DeadlineResult:
    """Resolve spoken phrases against `anchor` (the instant the user spoke), in `timezone`.

    `receipt` is the server receipt instant; when it moves the answer to a
    different day, that day is listed as an alternative but never substituted.
    """
    zone = ZoneInfo(timezone)
    local_anchor = anchor.astimezone(zone).replace(tzinfo=None)
    combined = normalize(" ".join(part for part in (date_phrase, time_phrase) if part))
    if not combined:
        return DeadlineResult()
    wall, time_warnings, remaining = _extract_time(combined)
    period_only = wall is None and re.search(r"\b(morning|afternoon|evening|night|tonight)\b", combined) is not None
    result = _parse_at(remaining, wall, local_anchor)
    result.warnings = [*time_warnings, *result.warnings]
    if period_only:
        result.warnings.append("time_period_only")
    if result.due_date is not None:
        if wall is not None:
            result.due_time = wall
            result.due_timezone = timezone
            if not time_exists(result.due_date, wall, timezone):
                result.warnings.append("dst_gap")
                shifted = (datetime.combine(result.due_date, wall) + timedelta(hours=1)).time()
                result.alternatives.append({"due_date": result.due_date.isoformat(), "due_time": shifted.isoformat()})
                result.due_time = None
                result.due_timezone = None
    if receipt is not None and result.relative and result.due_date is not None:
        local_receipt = receipt.astimezone(zone).replace(tzinfo=None)
        other = _parse_at(remaining, wall, local_receipt)
        if other.due_date is not None and other.due_date != result.due_date:
            result.alternatives.append({"due_date": other.due_date.isoformat(), "due_time": wall.isoformat() if wall else None, "anchor": "receipt"})
    return result
