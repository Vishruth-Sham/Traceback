from datetime import date, datetime, timedelta, timezone

import pytest

from processor.errors import InterpretationError, ModelUnavailableError
from processor.log_classifier import _parse, classify_day

IST = timezone(timedelta(hours=5, minutes=30))


def add(client, text, at=None, **headers):
    body = {"text": text}
    if at is not None:
        body["at"] = at
    return client.post("/api/v1/log", json=body, headers=headers)


def day_entries(client, day):
    return client.get(f"/api/v1/log/days/{day}").json()["entries"]


def test_entry_is_stored_as_written_and_assigned_to_its_day(client):
    response = add(client, "  Eggs and toast  ", at="2031-03-10T08:10:00+05:30")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["text"] == "Eggs and toast"
    assert body["log_date"] == "2031-03-10"
    assert body["origin"] == "ui"
    assert body["labels"] == []


def test_entries_before_day_start_belong_to_the_previous_day(client):
    late = add(client, "Bowl of cereal", at="2031-04-11T01:30:00+05:30").json()
    early = add(client, "Breakfast", at="2031-04-11T04:00:00+05:30").json()
    assert late["log_date"] == "2031-04-10"
    assert early["log_date"] == "2031-04-11"


def test_naive_time_is_read_in_the_user_timezone(client):
    entry = add(client, "Naive time", at="2031-05-02T02:00:00").json()
    assert entry["log_date"] == "2031-05-01"


def test_blank_and_oversized_text_are_rejected(client):
    assert add(client, "   ").status_code == 422
    assert add(client, "x" * 2001).status_code == 422
    assert client.post("/api/v1/log", json={"text": "ok", "unexpected": 1}).status_code == 422


def test_mcp_client_label_marks_origin(client):
    entry = add(client, "From Claude", at="2031-06-01T12:00:00+05:30", **{"X-Traceback-Client": "mcp"}).json()
    assert entry["origin"] == "mcp"


def test_day_lists_entries_in_time_order_and_days_newest_first(client):
    add(client, "later", at="2031-07-02T18:00:00+05:30")
    add(client, "earlier", at="2031-07-02T09:00:00+05:30")
    add(client, "other day", at="2031-07-01T09:00:00+05:30")
    assert [e["text"] for e in day_entries(client, "2031-07-02")] == ["earlier", "later"]
    days = client.get("/api/v1/log/days", params={"before": "2031-07-03", "limit": 2}).json()
    assert [d["log_date"] for d in days["days"]] == ["2031-07-02", "2031-07-01"]
    assert days["next_before"] == "2031-07-01"
    assert days["today"]


def test_days_paginate_with_before(client):
    for day in ("2031-08-03", "2031-08-02", "2031-08-01"):
        add(client, f"on {day}", at=f"{day}T12:00:00+05:30")
    first = client.get("/api/v1/log/days", params={"before": "2031-08-04", "limit": 2}).json()
    assert [d["log_date"] for d in first["days"]] == ["2031-08-03", "2031-08-02"]
    second = client.get("/api/v1/log/days", params={"before": first["next_before"], "limit": 2}).json()
    assert [d["log_date"] for d in second["days"]][:1] == ["2031-08-01"]


def test_range_returns_days_oldest_first_with_labels_summaries_and_skips_archived(client, monkeypatch):
    add(client, "first", at="2033-01-01T09:00:00+05:30")
    add(client, "second", at="2033-01-03T09:00:00+05:30")
    gone = add(client, "hidden", at="2033-01-02T09:00:00+05:30").json()
    add(client, "outside", at="2033-02-10T09:00:00+05:30")
    client.delete(f"/api/v1/log/{gone['id']}")
    monkeypatch.setattr("processor.log_classifier.classify_day", lambda entries, categories, **_: {"labels": [["work"]], "summary": "Done."})
    client.post("/api/v1/log/classify", json={"date": "2033-01-03"})
    body = client.get("/api/v1/log/range", params={"start": "2033-01-01", "end": "2033-01-31"}).json()
    assert [d["log_date"] for d in body["days"]] == ["2033-01-01", "2033-01-03"]
    assert body["days"][1]["summary"] == "Done."
    assert body["days"][1]["entries"][0]["labels"] == ["work"]
    assert body["days"][0]["summary"] is None


def test_range_rejects_backwards_and_oversized_spans(client):
    assert client.get("/api/v1/log/range", params={"start": "2033-02-02", "end": "2033-02-01"}).status_code == 422
    too_big = client.get("/api/v1/log/range", params={"start": "2033-01-01", "end": "2033-12-31"})
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "range_too_large"
    assert client.get("/api/v1/log/range", params={"start": "2033-01-01", "end": "2033-04-03"}).status_code == 200


def test_search_matches_text_case_insensitively_and_escapes_wildcards(client):
    add(client, "Lunch with Priya at the Udupi place", at="2031-09-01T13:00:00+05:30")
    add(client, "100% focus day", at="2031-09-01T14:00:00+05:30")
    assert [e["text"] for e in client.get("/api/v1/log/search", params={"q": "udupi"}).json()["entries"]] == [
        "Lunch with Priya at the Udupi place"
    ]
    assert [e["text"] for e in client.get("/api/v1/log/search", params={"q": "100%"}).json()["entries"]] == ["100% focus day"]
    assert client.get("/api/v1/log/search", params={"q": "%"}).json()["entries"][0]["text"] == "100% focus day"


def test_archive_hides_entry_and_is_idempotent(client):
    entry = add(client, "archive me", at="2031-10-01T10:00:00+05:30").json()
    assert client.delete(f"/api/v1/log/{entry['id']}").status_code == 204
    assert client.delete(f"/api/v1/log/{entry['id']}").status_code == 204
    assert day_entries(client, "2031-10-01") == []
    assert client.get("/api/v1/log/search", params={"q": "archive me"}).json()["entries"] == []
    assert client.delete("/api/v1/log/00000000-0000-0000-0000-000000000000").status_code == 404


def test_default_categories_exist_and_can_be_edited(client):
    names = [c["name"] for c in client.get("/api/v1/log/categories").json()]
    assert {"food", "exercise", "work"} <= set(names)
    created = client.post("/api/v1/log/categories", json={"name": " Caffeine ", "description": "Coffee, tea"}).json()
    assert created["name"] == "caffeine"
    assert client.post("/api/v1/log/categories", json={"name": "caffeine"}).status_code == 409
    patched = client.patch(f"/api/v1/log/categories/{created['id']}", json={"description": "Coffee"}).json()
    assert patched["description"] == "Coffee"
    assert client.patch(f"/api/v1/log/categories/{created['id']}", json={"name": "food"}).status_code == 409
    assert client.delete(f"/api/v1/log/categories/{created['id']}").status_code == 204
    assert "caffeine" not in [c["name"] for c in client.get("/api/v1/log/categories").json()]


def test_classify_stores_labels_and_summary_and_rerun_replaces_them(client, monkeypatch):
    add(client, "Eggs and toast", at="2032-01-05T08:10:00+05:30")
    add(client, "Gym, bench and rows", at="2032-01-05T15:40:00+05:30")
    calls = []

    def fake(entries, categories, **_):
        calls.append((entries, categories))
        return {"labels": [["food"], ["exercise", "health"]], "summary": "Ate, then lifted."}

    monkeypatch.setattr("processor.log_classifier.classify_day", fake)
    response = client.post("/api/v1/log/classify", json={"date": "2032-01-05"})
    assert response.status_code == 200, response.text
    assert response.json()["classified_days"] == ["2032-01-05"]
    assert calls[0][0][0] == {"time": "08:10", "text": "Eggs and toast"}
    day = client.get("/api/v1/log/days/2032-01-05").json()
    assert day["summary"] == "Ate, then lifted."
    assert [e["labels"] for e in day["entries"]] == [["food"], ["exercise", "health"]]

    monkeypatch.setattr(
        "processor.log_classifier.classify_day",
        lambda entries, categories, **_: {"labels": [[], ["exercise"]], "summary": "Second pass."},
    )
    client.post("/api/v1/log/classify", json={"date": "2032-01-05"})
    day = client.get("/api/v1/log/days/2032-01-05").json()
    assert day["summary"] == "Second pass."
    assert [e["labels"] for e in day["entries"]] == [[], ["exercise"]]
    # The original text is untouched by classification.
    assert [e["text"] for e in day["entries"]] == ["Eggs and toast", "Gym, bench and rows"]


def test_classify_reports_model_problems_without_changing_data(client, monkeypatch):
    add(client, "Something", at="2032-02-01T09:00:00+05:30")

    def unavailable(*_a, **_k):
        raise ModelUnavailableError("down")

    monkeypatch.setattr("processor.log_classifier.classify_day", unavailable)
    response = client.post("/api/v1/log/classify", json={"date": "2032-02-01"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"

    def broken(*_a, **_k):
        raise InterpretationError("bad")

    monkeypatch.setattr("processor.log_classifier.classify_day", broken)
    assert client.post("/api/v1/log/classify", json={"date": "2032-02-01"}).status_code == 502
    assert day_entries(client, "2032-02-01")[0]["labels"] == []


def test_classify_all_days_continues_past_a_failed_day(client, monkeypatch):
    add(client, "Day one", at="2032-03-01T09:00:00+05:30")
    add(client, "Day two", at="2032-03-02T09:00:00+05:30")

    def flaky(entries, categories, **_):
        if entries[0]["text"] == "Day one":
            raise InterpretationError("bad")
        return {"labels": [["work"]] * len(entries), "summary": "Fine."}

    monkeypatch.setattr("processor.log_classifier.classify_day", flaky)
    body = client.post("/api/v1/log/classify", json={"all_days": True}).json()
    assert date.fromisoformat("2032-03-01") in map(date.fromisoformat, body["failed_days"])
    assert "2032-03-02" in body["classified_days"]


class _Clock:
    """Stands in for `backend.log.datetime` so 'now' is fixed; nothing else about datetime changes."""

    def __init__(self, monkeypatch, iso):
        from datetime import datetime as real

        fixed = real.fromisoformat(iso)

        class Fixed(real):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed

        monkeypatch.setattr("backend.log.datetime", Fixed)


def _fake_classifier(monkeypatch, seen):
    def fake(entries, categories, **_):
        seen.append([e["text"] for e in entries])
        return {"labels": [["work"] for _ in entries], "summary": "Auto."}

    monkeypatch.setattr("processor.log_classifier.classify_day", fake)


def test_pending_only_classifies_finished_days_but_leaves_today_until_evening(client, monkeypatch):
    add(client, "finished day", at="2029-06-08T10:00:00+05:30")
    add(client, "today so far", at="2029-06-10T09:00:00+05:30")
    seen = []
    _fake_classifier(monkeypatch, seen)
    _Clock(monkeypatch, "2029-06-10T12:00:00+05:30")
    body = client.post("/api/v1/log/classify", json={"pending_only": True}).json()
    assert body["classified_days"] == ["2029-06-08"]
    assert seen == [["finished day"]]
    assert client.get("/api/v1/log/days/2029-06-10").json()["summary"] is None

    # Nothing left for the finished day; today is still waiting for the evening cut-off.
    assert client.post("/api/v1/log/classify", json={"pending_only": True}).json()["classified_days"] == []

    _Clock(monkeypatch, "2029-06-10T22:30:00+05:30")
    body = client.post("/api/v1/log/classify", json={"pending_only": True}).json()
    assert body["classified_days"] == ["2029-06-10"]
    assert client.get("/api/v1/log/days/2029-06-10").json()["summary"] == "Auto."


def test_pending_only_does_not_reclassify_a_day_that_already_has_a_summary(client, monkeypatch):
    add(client, "already done", at="2029-07-01T10:00:00+05:30")
    seen = []
    _fake_classifier(monkeypatch, seen)
    _Clock(monkeypatch, "2029-07-05T12:00:00+05:30")
    client.post("/api/v1/log/classify", json={"date": "2029-07-01"})
    seen.clear()
    assert client.post("/api/v1/log/classify", json={"pending_only": True}).json()["classified_days"] == []
    assert seen == []


def test_pending_only_swallows_a_model_failure_instead_of_erroring(client, monkeypatch):
    add(client, "model is down", at="2029-08-01T10:00:00+05:30")

    def down(*_a, **_k):
        raise ModelUnavailableError("down")

    monkeypatch.setattr("processor.log_classifier.classify_day", down)
    _Clock(monkeypatch, "2029-08-05T12:00:00+05:30")
    response = client.post("/api/v1/log/classify", json={"pending_only": True})
    assert response.status_code == 200
    assert response.json() == {"classified_days": [], "failed_days": ["2029-08-01"]}


def test_pending_only_cannot_be_combined_with_a_date_or_all_days(client):
    assert client.post("/api/v1/log/classify", json={"pending_only": True, "date": "2029-01-01"}).status_code == 422
    assert client.post("/api/v1/log/classify", json={"pending_only": True, "all_days": True}).status_code == 422


def test_log_requires_authentication(client):
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/log/days").status_code == 401
        assert anonymous.post("/api/v1/log", json={"text": "x"}).status_code == 401


CATEGORIES = [{"name": "food", "description": "Meals"}, {"name": "work", "description": "Job"}]


def test_parse_drops_unknown_labels_and_tolerates_missing_entries():
    parsed = _parse(
        '{"entries": [{"n": 1, "labels": ["food", "invented", "food"]}, {"n": 9, "labels": ["work"]}], "summary": " Ok. "}',
        2,
        {"food", "work"},
    )
    assert parsed == {"labels": [["food"], []], "summary": "Ok."}


@pytest.mark.parametrize("content", ["nope", "[]", '{"entries": [], "summary": ""}', '{"summary": "x"}'])
def test_parse_rejects_malformed_output(content):
    with pytest.raises(ValueError):
        _parse(content, 1, {"food"})


def test_classify_day_retries_once_then_succeeds(monkeypatch):
    replies = iter(["not json", '{"entries": [{"n": 1, "labels": ["food"]}], "summary": "Ate."}'])
    monkeypatch.setattr("processor.log_classifier._call_ollama", lambda messages, settings: next(replies))
    result = classify_day([{"time": "08:00", "text": "Eggs"}], CATEGORIES)
    assert result == {"labels": [["food"]], "summary": "Ate."}


def test_classify_day_gives_up_after_the_retry_budget(monkeypatch):
    monkeypatch.setattr("processor.log_classifier._call_ollama", lambda messages, settings: "still not json")
    with pytest.raises(InterpretationError):
        classify_day([{"time": "08:00", "text": "Eggs"}], CATEGORIES)
    with pytest.raises(InterpretationError):
        classify_day([], CATEGORIES)
