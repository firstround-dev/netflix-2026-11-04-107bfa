from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.translator import SourceQuestion
from tests.conftest import (
    QUESTION,
    add_question,
    all_translations,
    approve,
    approve_everything,
    create_set,
    draft_all,
    get_set,
    make_client,
)

# ----- sets and questions ----------------------------------------------------


def test_create_set_and_add_question(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR", "es-ES"])
    assert question_set["status"] == "draft"
    assert question_set["locales"] == ["es-ES", "fr-FR"]  # de-duplicated
    assert question_set["readiness"] == {
        "ready": False,
        "blockers": ["the set has no questions"],
        "per_locale": {
            "es-ES": {"total": 0, "approved": 0, "draft": 0, "rejected": 0, "missing": 0},
            "fr-FR": {"total": 0, "approved": 0, "draft": 0, "rejected": 0, "missing": 0},
        },
    }

    question = add_question(client, question_set["id"])
    assert question["position"] == 1
    assert question["created_by"] == "Dana"
    assert question["translations"] == {}

    listing = client.get("/api/sets").json()
    assert [(item["id"], item["question_count"], item["ready"]) for item in listing] == [(question_set["id"], 1, False)]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "", "locales": ["es-ES"], "created_by": "Dana"},
        {"title": "Ep", "locales": [], "created_by": "Dana"},
        {"title": "Ep", "locales": ["spanish"], "created_by": "Dana"},
        {"title": "Ep", "locales": ["es-ES"], "created_by": "   "},
        {"title": "Ep", "locales": ["es-ES"]},
    ],
)
def test_set_validation(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/sets", json=body).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"options": ["a", "b", "c"]},
        {"options": ["a", "b", "c", "d", "e"]},
        {"options": ["a", "b", "c", "a"]},
        {"options": ["a", "b", "c", ""]},
        {"correct_index": 4},
        {"correct_index": -1},
        {"prompt": " "},
        {"author": ""},
    ],
)
def test_question_validation(client: TestClient, overrides: dict[str, Any]) -> None:
    question_set = create_set(client)
    response = client.post(f"/api/sets/{question_set['id']}/questions", json={**QUESTION, **overrides})
    assert response.status_code == 422


def test_unknown_set_is_404(client: TestClient) -> None:
    assert client.get("/api/sets/nope").status_code == 404
    assert client.post("/api/sets/nope/questions", json=QUESTION).status_code == 404


# ----- drafting --------------------------------------------------------------


def test_drafts_are_created_for_every_question_and_locale(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR"])
    add_question(client, question_set["id"])
    add_question(client, question_set["id"], prompt="Largest ocean?", options=["Atlantic", "Indian", "Arctic", "Pacific"])

    result = draft_all(client, question_set["id"])
    assert result == {"created": 4, "skipped": 0, "failed": []}

    translations = all_translations(client, question_set["id"])
    assert len(translations) == 4
    assert {(t["status"], t["source"], t["updated_by"]) for t in translations} == {("draft", "ai", "Dana")}
    assert get_set(client, question_set["id"])["readiness"]["per_locale"]["es-ES"] == {
        "total": 2, "approved": 0, "draft": 2, "rejected": 0, "missing": 0,
    }

    # Running again does nothing: existing drafts are never silently replaced.
    assert draft_all(client, question_set["id"]) == {"created": 0, "skipped": 4, "failed": []}


def test_drafts_can_be_limited_to_one_locale(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR"])
    add_question(client, question_set["id"])
    assert draft_all(client, question_set["id"], locales=["fr-FR"]) == {"created": 1, "skipped": 0, "failed": []}
    assert list(get_set(client, question_set["id"])["questions"][0]["translations"]) == ["fr-FR"]

    response = client.post(f"/api/sets/{question_set['id']}/drafts", json={"requested_by": "Dana", "locales": ["de-DE"]})
    assert response.status_code == 422
    assert "de-DE" in response.json()["detail"]


def test_overwrite_never_touches_human_or_approved_text(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR", "de-DE"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    by_locale = {t["locale"]: t for t in all_translations(client, question_set["id"])}

    client.put(
        f"/api/translations/{by_locale['es-ES']['id']}",
        json={"prompt": "Humano", "options": ["a", "b", "c", "d"], "edited_by": "Keiko"},
    ).raise_for_status()
    approve(client, by_locale["fr-FR"]["id"])
    client.post(
        f"/api/translations/{by_locale['de-DE']['id']}/reject", json={"reviewer": "Keiko", "note": "try again"}
    ).raise_for_status()

    result = draft_all(client, question_set["id"], overwrite_drafts=True)
    assert result == {"created": 1, "skipped": 2, "failed": []}
    after = {t["locale"]: t for t in all_translations(client, question_set["id"])}
    assert after["es-ES"]["prompt"] == "Humano" and after["es-ES"]["source"] == "human"
    assert after["fr-FR"]["status"] == "approved"
    assert after["de-DE"]["status"] == "draft" and after["de-DE"]["review_note"] is None


class RecordingTranslator:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[SourceQuestion, str]] = []

    def translate(self, question: SourceQuestion, target_locale: str) -> object:
        self.calls.append((question, target_locale))
        return {"prompt": f"{target_locale}: {question.prompt}", "options": list(question.options)}


def test_translator_only_receives_question_text(tmp_path: Path) -> None:
    translator = RecordingTranslator()
    with make_client(tmp_path, translator) as client:
        question_set = create_set(client, locales=["es-ES"], title="Secret Episode Title")
        add_question(client, question_set["id"], author="Dana Producer")
        draft_all(client, question_set["id"])

    assert len(translator.calls) == 1
    question, locale = translator.calls[0]
    assert locale == "es-ES"
    assert question == SourceQuestion(prompt=QUESTION["prompt"], options=tuple(QUESTION["options"]))
    # The payload type has no room for anything but text: no names, titles or ids.
    assert [field.name for field in dataclasses.fields(question)] == ["prompt", "options"]


class ChaosTranslator:
    """Returns something different each call: wrong shape, HTML, an exception, then a good draft."""

    name = "chaos"

    def __init__(self) -> None:
        self.outputs: list[object] = [
            {"prompt": "three options", "options": ["a", "b", "c"]},
            {"prompt": "<img src=x onerror=alert(1)>", "options": ["<b>a</b>", "b", "c", "d"]},
            RuntimeError("vendor down"),
            "not even an object",
            {"prompt": "fine", "options": ["a", "b", "c", "d"]},
        ]

    def translate(self, question: SourceQuestion, target_locale: str) -> object:
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def test_bad_model_output_is_rejected_and_recorded(tmp_path: Path) -> None:
    with make_client(tmp_path, ChaosTranslator()) as client:
        question_set = create_set(client, locales=["es-ES", "fr-FR", "de-DE", "it-IT", "pt-BR"])
        add_question(client, question_set["id"])
        result = draft_all(client, question_set["id"])

        assert result["created"] == 2
        assert [(f["locale"], f["reason"]) for f in result["failed"]] == [
            ("es-ES", "rejected model output: expected 4 options, got 3"),
            ("de-DE", "translator error: RuntimeError"),
            ("it-IT", "rejected model output: draft must be an object with 'prompt' and 'options'"),
        ]

        translations = {t["locale"]: t for t in all_translations(client, question_set["id"])}
        assert set(translations) == {"fr-FR", "pt-BR"}
        # HTML is stored verbatim as text: it is the UI's job to escape it, and the linguist will see it.
        assert translations["fr-FR"]["prompt"] == "<img src=x onerror=alert(1)>"
        readiness = get_set(client, question_set["id"])["readiness"]["per_locale"]
        assert readiness["es-ES"]["missing"] == 1

        failures = [e for e in client.get(f"/api/sets/{question_set['id']}/events").json() if e["action"] == "draft_failed"]
        assert {(e["locale"], e["source"]) for e in failures} == {("es-ES", "ai"), ("de-DE", "ai"), ("it-IT", "ai")}


# ----- review ------------------------------------------------------------------


def test_approval_requires_a_named_reviewer(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]

    for body in ({}, {"reviewer": ""}, {"reviewer": "   "}):
        assert client.post(f"/api/translations/{translation['id']}/approve", json=body).status_code == 422

    approved = approve(client, translation["id"], reviewer="  Keiko ")
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "Keiko"
    assert approved["reviewed_at"] is not None
    assert approved["source"] == "ai"  # the text is still the machine's; the approval is Keiko's
    assert approved["version"] == translation["version"] + 1


def test_rejection_requires_a_note(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]

    assert client.post(f"/api/translations/{translation['id']}/reject", json={"reviewer": "Keiko"}).status_code == 422
    response = client.post(
        f"/api/translations/{translation['id']}/reject", json={"reviewer": "Keiko", "note": "Wrong register"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["review_note"] == "Wrong register"


def test_editing_makes_a_human_draft_that_still_needs_approval(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = approve(client, all_translations(client, question_set["id"])[0]["id"])

    response = client.put(
        f"/api/translations/{translation['id']}",
        json={
            "prompt": "¿Qué planeta se conoce como el Planeta Rojo?",
            "options": ["Venus", "Marte", "Júpiter", "Mercurio"],
            "edited_by": "Keiko",
            "expected_version": translation["version"],
        },
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["status"] == "draft"
    assert edited["source"] == "human"
    assert edited["updated_by"] == "Keiko"
    assert edited["reviewed_by"] is None
    assert get_set(client, question_set["id"])["readiness"]["ready"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"prompt": "x", "options": ["a", "b", "c"], "edited_by": "Keiko"},
        {"prompt": "x", "options": ["a", "b", "c", "c"], "edited_by": "Keiko"},
        {"prompt": "", "options": ["a", "b", "c", "d"], "edited_by": "Keiko"},
        {"prompt": "x", "options": ["a", "b", "c", "d"]},
    ],
)
def test_edit_validation(client: TestClient, body: dict[str, Any]) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]
    assert client.put(f"/api/translations/{translation['id']}", json=body).status_code == 422


def test_stale_version_is_refused(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]
    approve(client, translation["id"])  # someone else reviewed it first

    stale = {"reviewer": "Marcus", "expected_version": translation["version"]}
    response = client.post(f"/api/translations/{translation['id']}/approve", json=stale)
    assert response.status_code == 409
    assert "changed since you loaded it" in response.json()["detail"]


def test_changing_the_english_sends_translations_back_to_draft(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR"])
    question = add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    approve_everything(client, question_set["id"])
    assert get_set(client, question_set["id"])["readiness"]["ready"] is True

    # Only the correct answer moves: translations stay valid.
    client.put(f"/api/questions/{question['id']}", json={**QUESTION, "correct_index": 2}).raise_for_status()
    assert get_set(client, question_set["id"])["readiness"]["ready"] is True

    # The prompt changes: every translation needs a fresh look.
    response = client.put(f"/api/questions/{question['id']}", json={**QUESTION, "prompt": "Which planet is red?"})
    assert response.status_code == 200
    translations = all_translations(client, question_set["id"])
    assert {t["status"] for t in translations} == {"draft"}
    assert {t["review_note"] for t in translations} == {"English source changed; needs re-review"}
    assert get_set(client, question_set["id"])["readiness"]["ready"] is False


def test_deleting_a_question_removes_its_translations(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    question = add_question(client, question_set["id"])
    draft_all(client, question_set["id"])

    assert client.delete(f"/api/questions/{question['id']}").status_code == 422  # actor is required
    assert client.delete(f"/api/questions/{question['id']}", params={"actor": "Dana"}).status_code == 204
    assert get_set(client, question_set["id"])["questions"] == []


# ----- locking -----------------------------------------------------------------


def test_lock_is_refused_until_everything_is_approved(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES", "fr-FR"])
    lock = {"locked_by": "Dana"}

    response = client.post(f"/api/sets/{question_set['id']}/lock", json=lock)
    assert response.status_code == 409
    assert "no questions" in response.json()["detail"]

    add_question(client, question_set["id"])
    response = client.post(f"/api/sets/{question_set['id']}/lock", json=lock)
    assert response.status_code == 409
    assert "Q1 es-ES: missing" in response.json()["detail"]

    draft_all(client, question_set["id"])
    response = client.post(f"/api/sets/{question_set['id']}/lock", json=lock)
    assert response.status_code == 409
    assert "Q1 es-ES: draft" in response.json()["detail"]

    translations = {t["locale"]: t for t in all_translations(client, question_set["id"])}
    approve(client, translations["es-ES"]["id"])
    client.post(f"/api/translations/{translations['fr-FR']['id']}/reject", json={"reviewer": "Keiko", "note": "no"})
    response = client.post(f"/api/sets/{question_set['id']}/lock", json=lock)
    assert response.status_code == 409
    assert response.json()["detail"].endswith("Q1 fr-FR: rejected")

    approve(client, translations["fr-FR"]["id"])
    response = client.post(f"/api/sets/{question_set['id']}/lock", json=lock)
    assert response.status_code == 200, response.text
    locked = response.json()
    assert locked["status"] == "locked"
    assert locked["locked_by"] == "Dana"
    assert locked["locked_at"] is not None
    assert client.post(f"/api/sets/{question_set['id']}/lock", json=lock).status_code == 409


def test_locked_set_refuses_every_mutation(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    question = add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    approve_everything(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]
    assert client.post(f"/api/sets/{question_set['id']}/lock", json={"locked_by": "Dana"}).status_code == 200

    attempts = [
        client.post(f"/api/sets/{question_set['id']}/questions", json=QUESTION),
        client.put(f"/api/questions/{question['id']}", json={**QUESTION, "prompt": "Changed"}),
        client.delete(f"/api/questions/{question['id']}", params={"actor": "Dana"}),
        client.post(f"/api/sets/{question_set['id']}/drafts", json={"requested_by": "Dana", "overwrite_drafts": True}),
        client.put(
            f"/api/translations/{translation['id']}",
            json={"prompt": "x", "options": ["a", "b", "c", "d"], "edited_by": "Keiko"},
        ),
        client.post(f"/api/translations/{translation['id']}/approve", json={"reviewer": "Keiko"}),
        client.post(f"/api/translations/{translation['id']}/reject", json={"reviewer": "Keiko", "note": "x"}),
    ]
    for response in attempts:
        assert response.status_code == 409, (response.request.url, response.text)
        assert "locked" in response.json()["detail"]

    # Nothing changed.
    after = get_set(client, question_set["id"])
    assert after["status"] == "locked"
    assert [q["prompt"] for q in after["questions"]] == [QUESTION["prompt"]]
    assert after["questions"][0]["translations"]["es-ES"]["status"] == "approved"


# ----- audit trail -------------------------------------------------------------


def test_audit_trail_records_who_did_what_and_where_text_came_from(client: TestClient) -> None:
    question_set = create_set(client, locales=["es-ES"])
    add_question(client, question_set["id"])
    draft_all(client, question_set["id"])
    translation = all_translations(client, question_set["id"])[0]
    client.put(
        f"/api/translations/{translation['id']}",
        json={"prompt": "Edited", "options": ["a", "b", "c", "d"], "edited_by": "Keiko"},
    ).raise_for_status()
    approve(client, translation["id"], reviewer="Marcus")
    client.post(f"/api/sets/{question_set['id']}/lock", json={"locked_by": "Dana"}).raise_for_status()

    events = client.get(f"/api/sets/{question_set['id']}/events").json()
    assert [(e["action"], e["actor"], e["source"]) for e in reversed(events)] == [
        ("set_created", "Dana", None),
        ("question_added", "Dana", "human"),
        ("draft_created", "Dana", "ai"),
        ("translation_edited", "Keiko", "human"),
        ("translation_approved", "Marcus", "human"),
        ("set_locked", "Dana", None),
    ]
    assert all(e["at"] for e in events)
