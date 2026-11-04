"""Populate the database with a sample episode so the UI has something to show.

Run from the backend directory: `uv run python -m app.seed`
"""

from __future__ import annotations

import os
from pathlib import Path

from app.db import connect, init_schema
from app.service import Desk
from app.translator import build_translator

BACKEND_DIR = Path(__file__).resolve().parent.parent

SAMPLE_QUESTIONS = [
    ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Mercury"], 1),
    ("In which year did the first moon landing take place?", ["1965", "1967", "1969", "1971"], 2),
    ("Which instrument has 88 keys?", ["Guitar", "Violin", "Piano", "Trumpet"], 2),
    ("What is the largest ocean on Earth?", ["Atlantic", "Indian", "Arctic", "Pacific"], 3),
]


def main() -> None:
    db_path = Path(os.environ.get("TLD_DB_PATH", BACKEND_DIR / "data" / "trivia.db"))
    init_schema(db_path)
    conn = connect(db_path)
    try:
        desk = Desk(conn, build_translator("pseudo"))
        question_set = desk.create_set(
            title="Episode 12: Movie Night", locales=["es-ES", "pt-BR", "fr-FR"], created_by="Dana"
        )
        for prompt, options, correct_index in SAMPLE_QUESTIONS:
            desk.add_question(question_set["id"], prompt=prompt, options=options, correct_index=correct_index, author="Dana")
        desk.generate_drafts(question_set["id"], requested_by="Dana")

        # Leave the set in a mixed state so the readiness view has something to say.
        detail = desk.get_set(question_set["id"])
        first, second = detail["questions"][0], detail["questions"][1]
        desk.approve_translation(first["translations"]["es-ES"]["id"], reviewer="Keiko", expected_version=None)
        desk.edit_translation(
            second["translations"]["es-ES"]["id"],
            prompt="¿En qué año tuvo lugar el primer alunizaje?",
            options=["1965", "1967", "1969", "1971"],
            edited_by="Keiko",
            expected_version=None,
        )
        desk.reject_translation(
            first["translations"]["fr-FR"]["id"],
            reviewer="Keiko",
            note="Not translated, still the English prompt",
            expected_version=None,
        )
        print(f"Seeded '{question_set['title']}' ({question_set['id']}) into {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
