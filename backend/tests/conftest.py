from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.translator import PseudoTranslator, Translator


def make_client(tmp_path: Path, translator: Translator | None = None) -> TestClient:
    app = create_app(db_path=tmp_path / "test.db", translator=translator or PseudoTranslator())
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path) as test_client:
        yield test_client


QUESTION = {
    "prompt": "Which planet is known as the Red Planet?",
    "options": ["Venus", "Mars", "Jupiter", "Mercury"],
    "correct_index": 1,
    "author": "Dana",
}


def create_set(client: TestClient, locales: list[str] | None = None, title: str = "Episode 1") -> dict[str, Any]:
    response = client.post(
        "/api/sets", json={"title": title, "locales": locales or ["es-ES", "fr-FR"], "created_by": "Dana"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_question(client: TestClient, set_id: str, **overrides: Any) -> dict[str, Any]:
    response = client.post(f"/api/sets/{set_id}/questions", json={**QUESTION, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def draft_all(client: TestClient, set_id: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"/api/sets/{set_id}/drafts", json={"requested_by": "Dana", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def get_set(client: TestClient, set_id: str) -> dict[str, Any]:
    response = client.get(f"/api/sets/{set_id}")
    assert response.status_code == 200, response.text
    return response.json()


def all_translations(client: TestClient, set_id: str) -> list[dict[str, Any]]:
    detail = get_set(client, set_id)
    return [translation for question in detail["questions"] for translation in question["translations"].values()]


def approve(client: TestClient, translation_id: str, reviewer: str = "Keiko") -> dict[str, Any]:
    response = client.post(f"/api/translations/{translation_id}/approve", json={"reviewer": reviewer})
    assert response.status_code == 200, response.text
    return response.json()


def approve_everything(client: TestClient, set_id: str) -> None:
    for translation in all_translations(client, set_id):
        approve(client, translation["id"])
