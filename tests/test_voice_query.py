"""P0 read-only voice queries: deterministic classification, resolution, and the
guarantee that a query capture can never reach a mutation path.
"""
import uuid
from datetime import date, timedelta

import pytest

from backend.voice_policy.query import classify_query
from tests.test_voice_api import API, claim, now_ist, typed_voice, voice  # noqa: F401


def unique(label: str) -> str:
    return f"{label} {uuid.uuid4().hex[:8]}"


def resolve(client, capture, lease=None, **model):
    """`model` is Qwen's classification (`kind`, `phrase`); omitted, the backend lexicon classifies."""
    lease = lease or claim(client, capture)
    return client.post(
        f"{API}/captures/{capture['id']}/resolve-query",
        json={"expected_generation": lease["generation"], "lease_token": lease["lease_token"], **model},
    )


# ---- pure classifier ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,kind",
    [
        ("Show my overdue tasks", "overdue_tasks"),
        ("What tasks are late", "overdue_tasks"),
        ("What are my tasks", "all_tasks"),
        ("Show me all my tasks", "all_tasks"),
        ("What's in my inbox", "inbox_summary"),
        ("inbox summary", "inbox_summary"),
        ("Find my note about quantum entanglement", "search"),
        ("search for the kitchen project", "search"),
        ("Open the DSA Learning project", "navigate"),
        ("Can you open DSA Project", "navigate"),
        ("Can you open filmmaking in Learning", "navigate"),
        ("go to Renovation", "navigate"),
        ("Add a task to buy milk", "not_a_query"),
        ("Remind me to call mom tomorrow", "not_a_query"),
        ("", "not_a_query"),
    ],
)
def test_classify_query_kinds(text, kind):
    assert classify_query(text, has_followup_context=False).kind == kind


def test_ordinal_only_utterances_require_followup_context():
    assert classify_query("the first one", has_followup_context=False).kind == "not_a_query"
    result = classify_query("the first one", has_followup_context=True)
    assert result.kind == "followup_select" and result.index == 1
    assert classify_query("number three", has_followup_context=True).index == 3


# ---- overdue tasks --------------------------------------------------------------------------
def test_overdue_tasks_lists_only_open_overdue_tasks_with_late_meta(client, voice):  # noqa: F811
    title = unique("Overdue Query Task")
    task = client.post(
        f"{API}/items",
        json={"item_type": "task", "title": title, "due_date": (date.today() - timedelta(days=2)).isoformat()},
    ).json()
    capture = typed_voice(client, "Show my overdue tasks")
    response = resolve(client, capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_query"] is True
    result = body["query_result"]
    assert result["kind"] == "result" and result["label"] == "Overdue tasks"
    titles = {m["title"]: m for m in result["matches"]}
    assert title in titles and titles[title]["meta"] == "2d late" and titles[title]["route"] == f"/tasks?open={task['id']}"
    # the resolved capture never created or touched any item
    assert client.get(f"{API}/captures/{capture['id']}").json()["resulting_item_ids"] == []


def test_overdue_tasks_with_none_pending_says_so_instead_of_no_results(client, voice):  # noqa: F811
    capture = typed_voice(client, "What tasks are overdue")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "result"
    if not result["matches"]:
        assert "overdue" in (result["note"] or "").lower()


# ---- inbox summary --------------------------------------------------------------------------
def test_inbox_summary_lists_unclassified_notes(client, voice):  # noqa: F811
    title = unique("Inbox Query Note")
    client.post(f"{API}/items", json={"item_type": "note", "title": title, "content_md": "x"})
    capture = typed_voice(client, "What's in my inbox")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "result" and result["label"] == "Inbox"
    assert any(m["title"] == title for m in result["matches"])


# ---- search --------------------------------------------------------------------------------
def test_search_returns_matches_with_breadcrumbs(client, voice):  # noqa: F811
    title = unique("Zetabase Normal Forms")
    note = client.post(f"{API}/items", json={"item_type": "note", "title": title, "content_md": "about databases"}).json()
    capture = typed_voice(client, f"find {title}")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "result" and result["numbered"] is True
    match = next(m for m in result["matches"] if m["id"] == note["id"])
    assert match["path"] and match["route"] == f"/notes/{note['id']}"  # notes open their own page, never the side panel


def test_search_with_no_matches_is_a_distinct_no_results_state(client, voice):  # noqa: F811
    phrase = unique("Absolutely Nonexistent Phrase")
    capture = typed_voice(client, f"search for {phrase}")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "no_results" and "rephrasing" in result["note"]
    # the panel pins the full spoken command, not the internally cleaned search phrase
    assert result["query_text"] == f"search for {phrase}"


# ---- navigate --------------------------------------------------------------------------------
def test_navigate_to_a_unique_project_auto_confirms(client, voice):  # noqa: F811
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    title = unique("Voice Nav Solo Project")
    project = client.post(f"{API}/items", json={"item_type": "project", "title": title, "category_id": categories["projects"]}).json()
    capture = typed_voice(client, f"Open the {title} project")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "confirm"
    assert result["confirm"]["id"] == project["id"] and result["confirm"]["route"] == f"/projects/{project['id']}"


def test_navigate_uses_parent_qualifier_in_natural_in_phrase(client, voice):  # noqa: F811
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    title = unique("Filmmaking")
    learning = client.post(
        f"{API}/items", json={"item_type": "folder", "title": title, "category_id": categories["learning"]}
    ).json()
    client.post(f"{API}/items", json={"item_type": "folder", "title": title, "category_id": categories["projects"]})
    capture = typed_voice(client, f"Can you open {title} in Learning?")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "confirm"
    assert result["confirm"]["id"] == learning["id"]
    assert result["confirm"]["route"] == "/category/learning"  # a folder opens its listing, never the detail panel


def test_navigate_ambiguity_never_guesses_and_lists_every_candidate(client, voice):  # noqa: F811
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    title = unique("Renovation Collision")
    first = client.post(f"{API}/items", json={"item_type": "project", "title": title, "category_id": categories["projects"]}).json()
    second = client.post(f"{API}/items", json={"item_type": "folder", "title": title, "category_id": categories["learning"]}).json()
    capture = typed_voice(client, f"Open {title}")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "ambiguous" and result["numbered"] is True
    ids = {m["id"] for m in result["matches"]}
    assert {first["id"], second["id"]} == ids
    assert "never guesses" in result["note"]
    assert result["query_text"] == f"Open {title}"  # pinned exactly as spoken, matching the mockup


def test_navigate_with_no_match_is_no_results(client, voice):  # noqa: F811
    phrase = unique("Totally Missing Place")
    capture = typed_voice(client, f"go to {phrase}")
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "no_results"


# ---- numbered follow-up selection --------------------------------------------------------------
def test_followup_selection_resolves_against_the_prior_ambiguous_capture(client, voice):  # noqa: F811
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    title = unique("Followup Collision")
    first = client.post(f"{API}/items", json={"item_type": "project", "title": title, "category_id": categories["projects"]}).json()
    client.post(f"{API}/items", json={"item_type": "folder", "title": title, "category_id": categories["learning"]}).json()
    ambiguous_capture = typed_voice(client, f"Open {title}")
    ambiguous = resolve(client, ambiguous_capture).json()
    first_listed_id = ambiguous["query_result"]["matches"][0]["id"]

    followup_capture = typed_voice(client, "the first one", contextual_capture_id=ambiguous_capture["id"])
    response = resolve(client, followup_capture)
    result = response.json()["query_result"]
    assert result["kind"] == "confirm" and result["confirm"]["id"] == first_listed_id


def test_followup_without_a_valid_context_is_reported_not_silently_guessed(client, voice):  # noqa: F811
    capture = typed_voice(client, "the first one", contextual_capture_id=str(uuid.uuid4()))
    response = resolve(client, capture)
    result = response.json()["query_result"]
    assert result["kind"] == "no_results"


# ---- Qwen-supplied classification ------------------------------------------------------------------
def test_model_classification_resolves_wording_the_lexicon_cannot_match(client, voice):  # noqa: F811
    capture = typed_voice(client, "what tasks i have")
    assert classify_query("what tasks i have", has_followup_context=False).kind == "not_a_query"
    body = resolve(client, capture, kind="all_tasks").json()
    assert body["is_query"] is True
    assert body["query_result"]["kind"] == "result" and body["query_result"]["query_text"] == "what tasks i have"


def categories_by_slug(client):
    return {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}


def test_list_contents_of_the_projects_page_lists_projects(client, voice):  # noqa: F811
    title = unique("Aardvark Listed Project")
    project = client.post(f"{API}/items", json={"item_type": "project", "title": title, "category_id": categories_by_slug(client)["projects"]}).json()
    result = resolve(client, typed_voice(client, "Show all projects"), kind="list_contents", phrase="all projects").json()["query_result"]
    assert result["kind"] == "result" and result["label"] == "Projects" and result["footer_action"]["route"] == "/projects"
    assert any(m["id"] == project["id"] and m["route"] == f"/projects/{project['id']}" for m in result["matches"])


def test_list_contents_of_a_category_lists_only_its_top_level_items(client, voice):  # noqa: F811
    cats = categories_by_slug(client)
    # sorts first among folders, so the 10-row cap can never push it out however much the shared DB has accumulated
    top = client.post(f"{API}/items", json={"item_type": "folder", "title": unique("Aaaa TopFolder"), "category_id": cats["learning"]}).json()
    nested = client.post(f"{API}/items", json={"item_type": "note", "title": unique("NestedNote"), "content_md": "x", "category_id": cats["learning"], "parent_id": top["id"]})
    result = resolve(client, typed_voice(client, "what's in learning"), kind="list_contents", phrase="learning").json()["query_result"]
    assert result["kind"] == "result" and result["label"] == "In Learning" and result["footer_action"]["route"] == "/category/learning"
    ids = {m["id"] for m in result["matches"]}
    assert top["id"] in ids
    if nested.status_code < 300:
        assert nested.json()["id"] not in ids  # children of a folder are not top-level in the category


def test_list_contents_of_a_folder_lists_its_children_and_links_to_it(client, voice):  # noqa: F811
    cats = categories_by_slug(client)
    folder = client.post(f"{API}/items", json={"item_type": "folder", "title": unique("Filmmaking Listing"), "category_id": cats["learning"]}).json()
    empty = resolve(client, typed_voice(client, "what's in it"), kind="list_contents", phrase=folder["title"]).json()["query_result"]
    assert empty["kind"] == "result" and empty["matches"] == [] and "empty" in empty["note"]
    assert empty["footer_action"]["route"] == "/category/learning"


def test_list_contents_with_no_such_place_is_no_results(client, voice):  # noqa: F811
    result = resolve(client, typed_voice(client, "what's in nowhere"), kind="list_contents", phrase=unique("Nowhere Land")).json()["query_result"]
    assert result["kind"] == "no_results"


@pytest.mark.parametrize("spoken,route", [("inbox", "/inbox"), ("go to tasks", "/tasks"), ("projects", "/projects"), ("archive", "/archive"), ("skills", "/skills"), ("learning", "/category/learning")])
def test_navigate_opens_every_page_and_category(client, voice, spoken, route):  # noqa: F811
    phrase = spoken.removeprefix("go to ")
    result = resolve(client, typed_voice(client, f"open {phrase}"), kind="navigate", phrase=phrase).json()["query_result"]
    assert result["kind"] == "confirm" and result["confirm"]["route"] == route


def test_listing_archive_or_skills_just_opens_the_page(client, voice):  # noqa: F811
    result = resolve(client, typed_voice(client, "show archive"), kind="list_contents", phrase="archive").json()["query_result"]
    assert result["kind"] == "confirm" and result["confirm"]["route"] == "/archive"


def test_model_supplied_navigate_phrase_is_cleaned_and_resolved(client, voice):  # noqa: F811
    categories = {c["slug"]: c["id"] for c in client.get(f"{API}/categories").json()}
    title = unique("Model Nav Project")
    project = client.post(f"{API}/items", json={"item_type": "project", "title": title, "category_id": categories["projects"]}).json()
    capture = typed_voice(client, f"pull up the {title} project")
    result = resolve(client, capture, kind="navigate", phrase=f"the {title} project").json()["query_result"]
    assert result["kind"] == "confirm" and result["confirm"]["id"] == project["id"]


def test_model_kind_without_a_usable_phrase_falls_through_untouched(client, voice):  # noqa: F811
    capture = typed_voice(client, "open it")
    lease = claim(client, capture)
    body = resolve(client, capture, lease=lease, kind="navigate", phrase="  ").json()
    assert body["is_query"] is False
    assert client.get(f"{API}/captures/{capture['id']}").json()["processing"]["state"] == "processing"


def test_unknown_model_kind_is_rejected_by_the_schema(client, voice):  # noqa: F811
    capture = typed_voice(client, "delete everything")
    assert resolve(client, capture, kind="delete_all").status_code == 422


# ---- create commands still fall through untouched -----------------------------------------------
def test_a_create_command_is_not_classified_as_a_query_and_processing_state_is_untouched(client, voice):  # noqa: F811
    capture = typed_voice(client, "Add a task to buy milk tomorrow")
    lease = claim(client, capture)
    response = resolve(client, capture, lease=lease)
    body = response.json()
    assert body["is_query"] is False and "query_result" not in body
    refreshed = client.get(f"{API}/captures/{capture['id']}").json()
    assert refreshed["processing"]["state"] == "processing"  # the lease and generation are untouched; the create flow still owns it
    assert refreshed["processing"]["generation"] == lease["generation"]


# ---- fencing: query resolution is generation/lease fenced like every other processor step -------
def test_resolve_query_rejects_a_stale_generation(client, voice):  # noqa: F811
    capture = typed_voice(client, "Show my overdue tasks")
    lease = claim(client, capture)
    response = client.post(
        f"{API}/captures/{capture['id']}/resolve-query",
        json={"expected_generation": lease["generation"] + 1, "lease_token": lease["lease_token"]},
    )
    assert response.status_code == 409


def test_resolve_query_rejects_a_foreign_lease_token(client, voice):  # noqa: F811
    capture = typed_voice(client, "Show my overdue tasks")
    lease = claim(client, capture)
    response = client.post(
        f"{API}/captures/{capture['id']}/resolve-query",
        json={"expected_generation": lease["generation"], "lease_token": str(uuid.uuid4())},
    )
    assert response.status_code == 409


def test_resolve_query_cannot_run_twice_on_the_same_lease(client, voice):  # noqa: F811
    capture = typed_voice(client, "What's in my inbox")
    lease = claim(client, capture)
    first = resolve(client, capture, lease=lease)
    assert first.status_code == 200
    second = resolve(client, capture, lease=lease)
    assert second.status_code == 409  # the lease was cleared by the first resolution
