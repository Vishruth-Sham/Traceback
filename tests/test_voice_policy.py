"""Deterministic tests for the pure backend voice policy: no database, model, or microphone."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.voice_policy import evaluate
from backend.voice_policy.dates import parse_deadline
from backend.voice_policy.destinations import resolve_destination
from backend.voice_policy.text import is_grounded

IST = "Asia/Kolkata"
SAT = datetime(2026, 9, 26, 10, 14, tzinfo=ZoneInfo(IST))  # Saturday
FRI = datetime(2026, 10, 2, 10, 14, tzinfo=ZoneInfo(IST))  # Friday, 10:14

CATALOG = [
    {"kind": "category", "id": "cat-learning", "title": "Learning", "path": "Learning", "version": None},
    {"kind": "category", "id": "cat-health", "title": "Health & Food", "path": "Health & Food", "version": None},
    {"kind": "category", "id": "cat-projects", "title": "Projects", "path": "Projects", "version": None},
    {"kind": "folder", "id": "f-db", "title": "Database Systems", "path": "Learning / Database Systems", "version": 3},
    {"kind": "project", "id": "p-kitchen", "title": "Kitchen renovation", "path": "Projects / Kitchen renovation", "version": 2},
    {"kind": "folder", "id": "f-a", "title": "Recipes", "path": "Health & Food / Recipes", "version": 1},
    {"kind": "folder", "id": "f-b", "title": "Recipes", "path": "Learning / Recipes", "version": 4},
]


def dl(date_phrase, time_phrase=None, *, anchor=SAT, **kw):
    return parse_deadline(date_phrase, time_phrase, anchor=anchor, timezone=IST, **kw)


# ---- dates: weekday semantics ---------------------------------------------------------
@pytest.mark.parametrize(
    "anchor,phrase,time,expected,default_warnings",
    [
        (SAT, "tomorrow", None, "2026-09-27", []),
        (SAT, "today", None, "2026-09-26", []),
        (SAT, "Friday", None, "2026-10-02", []),  # bare weekday != today: next occurrence strictly after today
        (SAT, "this Friday", None, "2026-10-02", []),
        (SAT, "on Monday", None, "2026-09-28", []),
        (SAT, "in 3 days", None, "2026-09-29", []),
        (SAT, "in two weeks", None, "2026-10-10", []),
        (SAT, "day after tomorrow", None, "2026-09-28", []),
    ],
)
def test_relative_dates_are_eligible_without_warnings(anchor, phrase, time, expected, default_warnings):
    result = dl(phrase, time, anchor=anchor)
    assert result.due_date.isoformat() == expected
    assert result.warnings == default_warnings
    assert result.due_time is None and result.due_timezone is None  # date-only stays date-only


def test_next_friday_on_saturday_is_next_calendar_week_with_alternative():
    result = dl("next Friday", "5 PM")
    assert result.due_date.isoformat() == "2026-10-02"
    assert (result.due_time.isoformat(), result.due_timezone) == ("17:00:00", IST)
    assert result.warnings == ["date_ambiguous_next_weekday"]
    assert result.alternatives == [{"due_date": "2026-10-09", "due_time": "17:00:00"}]


def test_next_friday_on_wednesday_alternative_is_nearest_upcoming():
    wednesday = datetime(2026, 9, 23, 9, 0, tzinfo=ZoneInfo(IST))
    result = dl("next Friday", None, anchor=wednesday)
    assert result.due_date.isoformat() == "2026-10-02"
    assert result.alternatives[0]["due_date"] == "2026-09-25"


@pytest.mark.parametrize("weekday_offset", range(7))
def test_bare_and_next_weekday_are_never_in_the_past_for_every_anchor_weekday(weekday_offset):
    anchor = SAT + timedelta(days=weekday_offset)
    for name in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        bare = dl(name, None, anchor=anchor)
        assert bare.due_date > anchor.date() or "date_ambiguous_same_weekday" in bare.warnings
        nxt = dl(f"next {name}", None, anchor=anchor)
        assert nxt.due_date > anchor.date()
        # weeks are Monday-Sunday: "next X" always lands in the next calendar week
        assert nxt.due_date.isocalendar()[1] != anchor.isocalendar()[1]


def test_same_weekday_is_ambiguous_default_today_when_time_is_ahead():
    result = dl("Friday", "5 PM", anchor=FRI)
    assert result.due_date.isoformat() == "2026-10-02"
    assert result.warnings == ["date_ambiguous_same_weekday"]
    assert result.alternatives[0]["due_date"] == "2026-10-09"


def test_same_weekday_default_is_plus_seven_when_time_has_passed_or_absent():
    passed = dl("Friday", "9 AM", anchor=FRI)
    assert passed.due_date.isoformat() == "2026-10-09" and passed.alternatives[0]["due_date"] == "2026-10-02"
    assert dl("Friday", None, anchor=FRI).due_date.isoformat() == "2026-10-09"


def test_this_friday_said_on_friday():
    assert dl("this Friday", "5 PM", anchor=FRI).due_date.isoformat() == "2026-10-02"
    late = dl("this Friday", "9 AM", anchor=FRI)
    assert late.due_date.isoformat() == "2026-10-09" and "time_passed_today" in late.warnings


def test_time_of_day_interactions():
    passed = dl("today", "9 AM")
    assert passed.due_date.isoformat() == "2026-09-26" and "time_passed_today" in passed.warnings
    assert dl(None, "11 AM").due_date.isoformat() == "2026-09-26"
    rolled = dl(None, "9 AM")
    assert rolled.due_date.isoformat() == "2026-09-27" and "date_assumed" in rolled.warnings
    assert "meridiem_assumed" in dl("tomorrow", "at 5").warnings
    assert dl("tomorrow", "at 5").due_time.hour == 17
    assert dl("tomorrow", "17:30").due_time.isoformat() == "17:30:00"
    assert dl("tomorrow", "noon").due_time.hour == 12
    assert "time_midnight_ambiguous" in dl("Friday", "midnight").warnings
    assert "time_period_only" in dl("tonight").warnings


def test_month_day_rules():
    assert dl("October 5th").due_date.isoformat() == "2026-10-05"
    assert dl("5 October").due_date.isoformat() == "2026-10-05"
    assert dl("the twenty fifth of December").due_date.isoformat() == "2026-12-25"
    assert dl("September 26").due_date.isoformat() == "2026-09-26"  # on the anchor day is allowed
    assert dl("September 25").due_date.isoformat() == "2027-09-25"  # never a past date
    far = dl("September 25")
    assert "year_assumed" in far.warnings
    assert dl("October 5, 2027").due_date.isoformat() == "2027-10-05" and dl("October 5, 2027").warnings == []
    assert "year_two_digit" in dl("October 5, 27").warnings
    leap = dl("February 29", anchor=datetime(2026, 3, 1, 9, 0, tzinfo=ZoneInfo(IST)))
    assert leap.due_date.isoformat() == "2028-02-29"


def test_numeric_dates_are_never_guessed_when_ambiguous():
    ambiguous = dl("5/10")
    assert ambiguous.due_date is None
    assert {alt["due_date"] for alt in ambiguous.alternatives} == {"2026-10-05", "2027-05-10"}
    assert "date_numeric_ambiguous" in ambiguous.warnings
    unique = dl("25/12")
    assert unique.due_date.isoformat() == "2026-12-25" and "date_numeric_format" in unique.warnings
    assert dl("2027-03-04").due_date.isoformat() == "2027-03-04"


def test_past_phrases_resolve_as_spoken_and_are_flagged():
    assert dl("yesterday").due_date.isoformat() == "2026-09-25" and "deadline_past" in dl("yesterday").warnings
    last = dl("last Friday")
    assert last.due_date.isoformat() == "2026-09-25" and "deadline_past" in last.warnings


def test_unresolvable_phrases_leave_no_date():
    for phrase in ("next week", "end of the month", "soon"):
        result = dl(phrase)
        assert result.due_date is None and "date_unresolved" in result.warnings


@pytest.mark.parametrize(
    "zone,day,wall,exists",
    [
        ("America/New_York", "2026-03-08", "02:30", False),  # spring-forward gap
        ("America/New_York", "2026-11-01", "01:30", True),  # repeated hour still exists
        ("Europe/London", "2026-03-29", "01:30", False),
        ("Asia/Kolkata", "2026-03-08", "02:30", True),
        ("Australia/Lord_Howe", "2026-10-04", "02:15", False),  # 30-minute DST shift
    ],
)
def test_dst_gap_is_reported_never_silently_adjusted(zone, day, wall, exists):
    anchor = datetime(2026, 1, 1, 9, 0, tzinfo=ZoneInfo(zone))
    hour, minute = map(int, wall.split(":"))
    result = parse_deadline(day, f"{hour}:{minute:02d} am" if hour < 12 else wall, anchor=anchor, timezone=zone)
    assert result.due_date.isoformat() == day
    if exists:
        assert "dst_gap" not in result.warnings and result.due_time is not None
    else:
        assert "dst_gap" in result.warnings and result.due_time is None and result.alternatives


def test_skew_adds_receipt_anchored_alternative_but_never_replaces_the_anchor():
    late = SAT + timedelta(days=1, hours=3)  # ingested the next day
    result = dl("tomorrow", None, receipt=late)
    assert result.due_date.isoformat() == "2026-09-27"  # captured_at anchor wins
    assert {"due_date": "2026-09-28", "due_time": None, "anchor": "receipt"} in result.alternatives


# ---- destinations ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "phrase,status,chosen,confidence",
    [
        ("Learning / Database Systems", "resolved", "f-db", "high"),
        ("Learning slash Database Systems", "resolved", "f-db", "high"),
        ("learning then database systems", "resolved", "f-db", "high"),
        ("Database Systems", "resolved", "f-db", "medium"),
        ("in project Kitchen renovation", "resolved", "p-kitchen", "medium"),
        ("Kitchen renovation project", "not_found", None, None),
        ("Learning", "resolved", "cat-learning", "high"),
        ("health and food", "resolved", "cat-health", "high"),
        ("Health food / Recipes", "resolved", "f-a", "high"),
        ("Recipes", "ambiguous", None, None),
        ("Kitchen renovaton", "resolved", "p-kitchen", "low"),
        ("Garage cleanup", "not_found", None, None),
        (None, "none", None, None),
    ],
)
def test_destination_resolution_table(phrase, status, chosen, confidence):
    result = resolve_destination(phrase, CATALOG)
    assert result["status"] == status
    assert (result["chosen"] or {}).get("id") == chosen
    assert result["confidence"] == confidence


def test_duplicate_names_never_preselect_and_qualifier_restricts_kind():
    result = resolve_destination("Recipes", CATALOG)
    assert result["chosen"] is None and {c["id"] for c in result["candidates"]} == {"f-a", "f-b"}
    assert resolve_destination("in folder Kitchen renovation", CATALOG)["status"] == "not_found"  # it is a project


def test_archived_containers_are_absent_from_the_catalog_so_cannot_resolve():
    without = [entry for entry in CATALOG if entry["id"] != "f-db"]
    assert resolve_destination("Learning / Database Systems", without)["status"] == "not_found"


def test_grounding_is_word_bounded_and_punctuation_insensitive():
    assert is_grounded("submit the report", "Remind me to submit the report next Friday.")
    assert is_grounded("5 PM", "at 5 p.m.")
    assert not is_grounded("submit the reports", "submit the report")
    assert not is_grounded("port", "submit the report")


# ---- full proposals -------------------------------------------------------------------
def slots(**overrides):
    base = dict(intent=None, title=None, content=None, destination_phrase=None, target_phrase=None, date_phrase=None, time_phrase=None, flags=[], reason="r")
    base.update(overrides)
    return base


def run(transcript, slot_values, *, captured=SAT, received=None, now=None, **kw):
    return evaluate(
        transcript=transcript, slots=slots(**slot_values), captured_at=captured,
        received_at=received or captured + timedelta(seconds=2), source_timezone=IST,
        now=now or captured + timedelta(seconds=30), catalog=CATALOG, **kw,
    )


def test_seed_note_with_folder_destination():
    proposal = run(
        "Add a note called Normal forms in Learning / Database Systems",
        dict(intent="create_note", title="Normal forms", destination_phrase="Learning / Database Systems"),
    )
    operation = proposal["operation"]
    assert (proposal["intent"], operation["item_type"], operation["title"], operation["content_md"]) == ("create_note", "note", "Normal forms", "")
    assert operation["destination"]["id"] == "f-db" and operation["destination"]["version"] == 3
    assert proposal["warnings"] == [] and proposal["disposition"] == "review"


def test_seed_generic_add_x_in_project_is_inferred_note_and_review():
    proposal = run("Add Vendor comparison in project Kitchen renovation", dict(intent="create_note", title="Vendor comparison", destination_phrase="project Kitchen renovation"))
    assert proposal["intent"] == "create_note" and "intent_inferred" in proposal["warnings"]
    assert proposal["operation"]["destination"]["id"] == "p-kitchen"
    assert proposal["resolution"]["intent"]["basis"] == "inferred_add_noun"


def test_seed_reminder_next_friday_5pm():
    proposal = run("Remind me to submit the report next Friday at 5 PM", dict(intent="create_task", title="submit the report", date_phrase="next Friday", time_phrase="5 PM"))
    operation = proposal["operation"]
    assert operation["title"] == "Submit the report"
    assert (operation["due_date"], operation["due_time"], operation["due_timezone"]) == ("2026-10-02", "17:00:00", IST)
    assert proposal["warnings"] == ["date_ambiguous_next_weekday"] and proposal["disposition"] == "review"
    assert proposal["resolution"]["date"]["alternatives"] == [{"due_date": "2026-10-09", "due_time": "17:00:00"}]
    assert proposal["resolution"]["intent"]["basis"] == "explicit_reminder_verb"


def test_verb_add_is_a_task_and_deadline_makes_it_inferred():
    proposal = run("Submit the report by Friday", dict(intent="create_task", title="Submit the report", date_phrase="Friday"))
    assert proposal["operation"]["item_type"] == "task" and proposal["operation"]["due_date"] == "2026-10-02"
    assert "intent_inferred" in proposal["warnings"]
    task = run("Add call the plumber in project Kitchen renovation", dict(intent="create_task", title="call the plumber", destination_phrase="project Kitchen renovation"))
    assert task["operation"]["item_type"] == "task" and task["operation"]["destination"]["id"] == "p-kitchen"


def test_note_noun_object_of_add_wins_over_remind_me_with_conflict():
    proposal = run("Add a note to remind me to call mom tomorrow", dict(intent="create_task", title="call mom", date_phrase="tomorrow"))
    assert proposal["intent"] == "create_note" and "intent_conflict" in proposal["warnings"]
    assert proposal["resolution"]["intent"]["alternative"] == "create_task"


def test_unclear_utterance_is_ambiguous_and_writes_nothing():
    proposal = run("Dad's birthday gift ideas", dict(intent="create_task", title="Dad's birthday gift ideas"))
    assert proposal["intent"] == "ambiguous" and proposal["operation"] is None and proposal["disposition"] == "review"
    only = run("Dad's birthday gift ideas", dict(intent="capture_only"))
    assert only["intent"] == "capture_only" and only["operation"] is None


@pytest.mark.parametrize("transcript,model_intent", [("Delete my old notes", "unsupported"), ("Delete my old notes", "create_note"), ("delete all my tasks", "create_task")])
def test_deletion_is_rejected_regardless_of_model_intent(transcript, model_intent):
    proposal = run(transcript, dict(intent=model_intent, title="old notes"))
    assert proposal["intent"] == "unsupported" and proposal["disposition"] == "reject" and proposal["operation"] is None


def test_organization_intents_are_unsupported_and_never_write():
    for transcript, intent in (("Move the report note to Learning", "move_item"), ("Mark buy milk as done", "complete_task"), ("archive my kitchen note", "archive_item")):
        proposal = run(transcript, dict(intent=intent, target_phrase="the report note"))
        assert proposal["intent"] == "unsupported" and proposal["operation"] is None
        assert proposal["disposition_reasons"] == ["organization_not_available"]


def test_restricted_launcher_rejects_out_of_scope_intent():
    proposal = run("Add a note called X", dict(intent="create_note", title="X"), allowed_intents=["create_task"])
    assert proposal["intent"] == "unsupported" and proposal["disposition"] == "reject"
    assert proposal["disposition_reasons"] == ["restricted_launcher"] and proposal["operation"] is None
    allowed = run("Add a task to book the venue", dict(intent="create_task", title="book the venue"), allowed_intents=["create_task"])
    assert allowed["operation"]["item_type"] == "task"


def test_surface_context_only_fills_a_missing_destination_and_forces_review():
    hinted = run("Add a task to book the venue", dict(intent="create_task", title="book the venue"), contextual_id="p-kitchen")
    assert hinted["operation"]["destination"] == {**hinted["operation"]["destination"], "id": "p-kitchen", "source": "surface_context"}
    assert "destination_from_context" in hinted["warnings"]
    spoken = run("Add a task to book the venue in Database Systems", dict(intent="create_task", title="book the venue", destination_phrase="Database Systems"), contextual_id="p-kitchen")
    assert spoken["operation"]["destination"]["id"] == "f-db" and spoken["operation"]["destination"]["source"] == "spoken"


def test_destination_states_become_review_warnings():
    missing = run("Add a note called X in Garage cleanup", dict(intent="create_note", title="X", destination_phrase="Garage cleanup"))
    assert missing["operation"]["destination"] is None and "destination_not_found" in missing["warnings"]
    ambiguous = run("Add a note called X in Recipes", dict(intent="create_note", title="X", destination_phrase="Recipes"))
    assert ambiguous["operation"]["destination"] is None and "destination_ambiguous" in ambiguous["warnings"]
    fuzzy = run("Add a note called X in Kitchen renovaton", dict(intent="create_note", title="X", destination_phrase="Kitchen renovaton"))
    assert "destination_fuzzy" in fuzzy["warnings"]


def test_hallucinated_spans_are_dropped_and_flagged():
    proposal = run(
        "Remind me to call mom tomorrow",
        dict(intent="create_task", title="Wire the money to my landlord", date_phrase="next Monday", destination_phrase="Secret folder"),
    )
    assert "ungrounded_text" in proposal["warnings"]
    # The hallucinated date phrase is dropped, so no deadline is set and the spoken words stay in the derived title.
    assert proposal["operation"]["title"] == "Call mom tomorrow"
    assert proposal["operation"]["due_date"] is None and proposal["operation"]["destination"] is None


def test_processor_flags_only_add_review_and_backend_flags_cannot_be_removed():
    clean = run("Remind me to call mom", dict(intent="create_task", title="call mom"))
    assert clean["warnings"] == []
    flagged = run("Remind me to call mom", dict(intent="create_task", title="call mom", flags=["unclear_audio"]))
    assert "unclear_audio" in flagged["warnings"]
    corrected = run("Remind me to call mom, no wait, call dad", dict(intent="create_task", title="call mom", flags=[]))
    assert "self_correction" in corrected["warnings"]  # derived by the backend even though the model reported none


def test_multi_intent_is_flagged_for_review():
    proposal = run("Remind me to call mom and then remind me to email Sam", dict(intent="create_task", title="call mom"))
    assert "multi_intent" in proposal["warnings"]


def test_model_confidence_never_changes_the_outcome():
    a = run("Remind me to call mom", dict(intent="create_task", title="call mom"), model_confidence="high")
    b = run("Remind me to call mom", dict(intent="create_task", title="call mom"), model_confidence="low")
    for key in ("operation", "warnings", "disposition", "disposition_reasons", "intent"):
        assert a[key] == b[key]
    assert a["model_confidence"] == "high"  # stored for offline evaluation only


def test_auto_apply_is_disabled_by_default_and_narrow_when_enabled_in_the_pure_policy():
    base = dict(intent="create_task", title="call mom")
    assert run("Remind me to call mom", base)["disposition"] == "review"
    assert "auto_apply_disabled" in run("Remind me to call mom", base)["disposition_reasons"]
    eligible = run("Remind me to call mom", base, auto_apply_intents=["create_task"])
    assert eligible["disposition"] == "auto_apply_eligible"
    # each disqualifier keeps it in review
    assert run("Remind me to call mom", base, auto_apply_intents=["create_task"], entry_point="mcp_typed")["disposition"] == "review"
    assert run("Remind me to call mom in Kitchen renovation", dict(**base, destination_phrase="Kitchen renovation"), auto_apply_intents=["create_task"])["disposition"] == "review"
    assert run("Add a note called X", dict(intent="create_note", title="X"), auto_apply_intents=["create_task"])["disposition"] == "review"
    assert run("Submit the report", dict(intent="create_task", title="Submit the report"), auto_apply_intents=["create_task"])["disposition"] == "review"  # inferred


def test_past_deadline_is_flagged_and_never_auto_apply_eligible():
    proposal = run("Remind me to call mom today at 9 AM", dict(intent="create_task", title="call mom", date_phrase="today", time_phrase="9 AM"), auto_apply_intents=["create_task"])
    assert "deadline_past" in proposal["warnings"] and proposal["disposition"] == "review"
    date_only = run("Remind me to call mom yesterday", dict(intent="create_task", title="call mom", date_phrase="yesterday"))
    assert "deadline_past" in date_only["warnings"]


def test_delayed_ingest_and_clock_ahead_force_review_and_keep_the_captured_anchor():
    delayed = run("Remind me to call mom tomorrow", dict(intent="create_task", title="call mom", date_phrase="tomorrow"), received=SAT + timedelta(hours=27))
    assert "delayed_ingest" in delayed["warnings"] and delayed["operation"]["due_date"] == "2026-09-27"
    assert delayed["resolution"]["anchor"]["captured_at"] == SAT.isoformat() and delayed["resolution"]["anchor"]["skew_s"] == 27 * 3600
    assert any(alt.get("anchor") == "receipt" for alt in delayed["resolution"]["date"]["alternatives"])
    ahead = run("Remind me to call mom tomorrow", dict(intent="create_task", title="call mom", date_phrase="tomorrow"), received=SAT - timedelta(minutes=10))
    assert "clock_ahead" in ahead["warnings"]
    absolute = run("Remind me to call mom on October 5, 2027", dict(intent="create_task", title="call mom", date_phrase="October 5, 2027"), received=SAT + timedelta(hours=27))
    assert "delayed_ingest" not in absolute["warnings"]  # absolute dates are unaffected by skew


def test_non_english_transcripts_need_review():
    proposal = run("メモを追加してください 明日", dict(intent="create_note", title="メモ"))
    assert "unsupported_language" in proposal["warnings"]


def test_duplicate_title_warning_uses_the_injected_lookup():
    proposal = run("Remind me to call mom", dict(intent="create_task", title="call mom"), title_exists=lambda title: title == "Call mom")
    assert "possible_duplicate" in proposal["warnings"]


def test_inputs_hash_changes_when_evidence_changes():
    a = run("Remind me to call mom", dict(intent="create_task", title="call mom"))
    b = run("Remind me to call mom", dict(intent="create_task", title="call mom"), contextual_id="p-kitchen")
    assert a["inputs_sha256"] != b["inputs_sha256"]
