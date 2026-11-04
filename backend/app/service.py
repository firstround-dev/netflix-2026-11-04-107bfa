"""Domain logic for the Trivia Localisation Desk.

Every rule that protects what goes to air lives here, not in the UI:

- translator output is validated before it is stored,
- only a named human can approve a translation,
- a set locks only when every question is approved in every locale,
- a locked set refuses every mutation,
- every change records who made it and whether the text came from AI or a human.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app.translator import DraftValidationError, SourceQuestion, TranslationDraft, Translator, parse_draft

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_MISSING = "missing"  # virtual: no translation row exists yet

SOURCE_AI = "ai"
SOURCE_HUMAN = "human"

SET_DRAFT = "draft"
SET_LOCKED = "locked"

SET_FIELDS = ("id", "title", "locales", "status", "created_by", "created_at", "locked_by", "locked_at")


class DomainError(Exception):
    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class SetLockedError(DomainError):
    status_code = 409


class ConflictError(DomainError):
    status_code = 409


class ValidationFailed(DomainError):
    status_code = 422


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE takes the write lock up front so check-then-write sequences cannot interleave."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _set_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "locales": json.loads(row["locales"]),
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "locked_by": row["locked_by"],
        "locked_at": row["locked_at"],
    }


def _question_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "set_id": row["set_id"],
        "position": row["position"],
        "prompt": row["prompt"],
        "options": json.loads(row["options"]),
        "correct_index": row["correct_index"],
        "created_by": row["created_by"],
        "updated_at": row["updated_at"],
        "translations": {},
    }


def _translation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "question_id": row["question_id"],
        "locale": row["locale"],
        "prompt": row["prompt"],
        "options": json.loads(row["options"]),
        "status": row["status"],
        "source": row["source"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"],
        "version": row["version"],
    }


def compute_readiness(locales: Sequence[str], questions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A set is ready when it has questions and every question is approved in every locale."""
    per_locale: dict[str, Counter[str]] = {locale: Counter() for locale in locales}
    blockers: list[str] = []
    for index, question in enumerate(questions, start=1):
        for locale in locales:
            translation = question["translations"].get(locale)
            status = translation["status"] if translation else STATUS_MISSING
            per_locale[locale][status] += 1
            if status != STATUS_APPROVED:
                blockers.append(f"Q{index} {locale}: {status}")
    if not questions:
        blockers.append("the set has no questions")
    if not locales:
        blockers.append("the set has no target locales")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "per_locale": {
            locale: {
                "total": len(questions),
                "approved": counts[STATUS_APPROVED],
                "draft": counts[STATUS_DRAFT],
                "rejected": counts[STATUS_REJECTED],
                "missing": counts[STATUS_MISSING],
            }
            for locale, counts in per_locale.items()
        },
    }


class Desk:
    """All operations on question sets. One instance per request, wrapping one connection."""

    def __init__(self, conn: sqlite3.Connection, translator: Translator) -> None:
        self._conn = conn
        self._translator = translator

    # ----- lookups ---------------------------------------------------------

    def _set_row(self, set_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM question_sets WHERE id = ?", (set_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"question set {set_id} not found")
        return _set_from_row(row)

    def _question_row(self, question_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"question {question_id} not found")
        return _question_from_row(row)

    def _translation_row(self, translation_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM translations WHERE id = ?", (translation_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"translation {translation_id} not found")
        return _translation_from_row(row)

    def _require_unlocked(self, set_id: str) -> dict[str, Any]:
        question_set = self._set_row(set_id)
        if question_set["status"] == SET_LOCKED:
            raise SetLockedError("this set is locked for broadcast and can no longer change")
        return question_set

    def _log(
        self,
        set_id: str,
        actor: str,
        action: str,
        *,
        question_id: str | None = None,
        translation_id: str | None = None,
        locale: str | None = None,
        source: str | None = None,
        detail: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO events (set_id, question_id, translation_id, locale, actor, action, source, detail, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (set_id, question_id, translation_id, locale, actor, action, source, detail, _now()),
        )

    # ----- question sets ---------------------------------------------------

    def list_sets(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT id FROM question_sets ORDER BY created_at DESC, rowid DESC").fetchall()
        summaries = []
        for row in rows:
            detail = self.get_set(row["id"])
            summaries.append(
                {
                    **{field: detail[field] for field in SET_FIELDS},
                    "question_count": len(detail["questions"]),
                    "ready": detail["readiness"]["ready"],
                }
            )
        return summaries

    def create_set(self, *, title: str, locales: Sequence[str], created_by: str) -> dict[str, Any]:
        set_id = _new_id()
        unique_locales = list(dict.fromkeys(locales))
        with _transaction(self._conn):
            self._conn.execute(
                "INSERT INTO question_sets (id, title, locales, status, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (set_id, title, json.dumps(unique_locales), SET_DRAFT, created_by, _now()),
            )
            self._log(set_id, created_by, "set_created", detail=f"locales: {', '.join(unique_locales)}")
        return self.get_set(set_id)

    def get_set(self, set_id: str) -> dict[str, Any]:
        question_set = self._set_row(set_id)
        question_rows = self._conn.execute(
            "SELECT * FROM questions WHERE set_id = ? ORDER BY position", (set_id,)
        ).fetchall()
        questions = [_question_from_row(row) for row in question_rows]
        by_id = {question["id"]: question for question in questions}
        translation_rows = self._conn.execute(
            "SELECT t.* FROM translations t JOIN questions q ON q.id = t.question_id WHERE q.set_id = ?",
            (set_id,),
        ).fetchall()
        for row in translation_rows:
            translation = _translation_from_row(row)
            by_id[translation["question_id"]]["translations"][translation["locale"]] = translation
        return {
            **question_set,
            "questions": questions,
            "readiness": compute_readiness(question_set["locales"], questions),
        }

    def list_events(self, set_id: str) -> list[dict[str, Any]]:
        self._set_row(set_id)
        rows = self._conn.execute("SELECT * FROM events WHERE set_id = ? ORDER BY id DESC", (set_id,)).fetchall()
        return [dict(row) for row in rows]

    def lock_set(self, set_id: str, *, locked_by: str) -> dict[str, Any]:
        with _transaction(self._conn):
            detail = self.get_set(set_id)
            if detail["status"] == SET_LOCKED:
                raise SetLockedError("this set is already locked")
            readiness = detail["readiness"]
            if not readiness["ready"]:
                shown = readiness["blockers"][:8]
                hidden = len(readiness["blockers"]) - len(shown)
                suffix = f" (and {hidden} more)" if hidden > 0 else ""
                raise ConflictError("the set is not ready to lock: " + "; ".join(shown) + suffix)
            self._conn.execute(
                "UPDATE question_sets SET status = ?, locked_by = ?, locked_at = ? WHERE id = ?",
                (SET_LOCKED, locked_by, _now(), set_id),
            )
            self._log(
                set_id,
                locked_by,
                "set_locked",
                detail=f"{len(detail['questions'])} questions approved in {len(detail['locales'])} locales",
            )
        return self.get_set(set_id)

    # ----- questions -------------------------------------------------------

    def add_question(
        self, set_id: str, *, prompt: str, options: Sequence[str], correct_index: int, author: str
    ) -> dict[str, Any]:
        question_id = _new_id()
        with _transaction(self._conn):
            self._require_unlocked(set_id)
            next_position = self._conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM questions WHERE set_id = ?", (set_id,)
            ).fetchone()[0]
            self._conn.execute(
                "INSERT INTO questions (id, set_id, position, prompt, options, correct_index, created_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (question_id, set_id, next_position, prompt, json.dumps(list(options)), correct_index, author, _now()),
            )
            self._log(set_id, author, "question_added", question_id=question_id, source=SOURCE_HUMAN)
        return self._question_row(question_id)

    def update_question(
        self, question_id: str, *, prompt: str, options: Sequence[str], correct_index: int, author: str
    ) -> dict[str, Any]:
        with _transaction(self._conn):
            question = self._question_row(question_id)
            self._require_unlocked(question["set_id"])
            self._conn.execute(
                "UPDATE questions SET prompt = ?, options = ?, correct_index = ?, updated_at = ? WHERE id = ?",
                (prompt, json.dumps(list(options)), correct_index, _now(), question_id),
            )
            self._log(question["set_id"], author, "question_updated", question_id=question_id, source=SOURCE_HUMAN)
            if prompt != question["prompt"] or list(options) != question["options"]:
                self._invalidate_translations(question, author)
        return self.get_question(question_id)

    def _invalidate_translations(self, question: dict[str, Any], author: str) -> None:
        """The English changed, so every existing translation must be reviewed again."""
        affected = self._conn.execute(
            "UPDATE translations SET status = ?, reviewed_by = NULL, reviewed_at = NULL, review_note = ?,"
            " version = version + 1 WHERE question_id = ? AND status != ?",
            (STATUS_DRAFT, "English source changed; needs re-review", question["id"], STATUS_DRAFT),
        ).rowcount
        if affected:
            self._log(
                question["set_id"],
                author,
                "translations_invalidated",
                question_id=question["id"],
                detail=f"{affected} translation(s) sent back to draft",
            )

    def get_question(self, question_id: str) -> dict[str, Any]:
        question = self._question_row(question_id)
        rows = self._conn.execute("SELECT * FROM translations WHERE question_id = ?", (question_id,)).fetchall()
        for row in rows:
            translation = _translation_from_row(row)
            question["translations"][translation["locale"]] = translation
        return question

    def delete_question(self, question_id: str, *, actor: str) -> None:
        with _transaction(self._conn):
            question = self._question_row(question_id)
            self._require_unlocked(question["set_id"])
            self._conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
            self._log(question["set_id"], actor, "question_deleted", question_id=question_id)

    # ----- drafting --------------------------------------------------------

    def generate_drafts(
        self,
        set_id: str,
        *,
        requested_by: str,
        locales: Sequence[str] | None = None,
        overwrite_drafts: bool = False,
    ) -> dict[str, Any]:
        """Draft a translation for every (question, locale) pair that needs one.

        Existing translations are skipped unless `overwrite_drafts` is set, and even then
        only untouched AI output (draft or rejected, never edited by a human) is replaced.
        """
        self._require_unlocked(set_id)
        detail = self.get_set(set_id)
        target_locales = detail["locales"] if locales is None else list(dict.fromkeys(locales))
        unknown = [locale for locale in target_locales if locale not in detail["locales"]]
        if unknown:
            raise ValidationFailed(f"locale(s) not in this set: {', '.join(unknown)}")

        created = 0
        skipped = 0
        failed: list[dict[str, str]] = []
        for question in detail["questions"]:
            for locale in target_locales:
                existing = question["translations"].get(locale)
                if existing is not None and not _is_replaceable(existing, overwrite_drafts):
                    skipped += 1
                    continue
                reason = self._draft_one(question, locale, requested_by=requested_by)
                if reason is None:
                    created += 1
                else:
                    failed.append({"question_id": question["id"], "locale": locale, "reason": reason})
        return {"created": created, "skipped": skipped, "failed": failed}

    def _draft_one(self, question: dict[str, Any], locale: str, *, requested_by: str) -> str | None:
        """Draft a single translation. Returns None on success, otherwise the failure reason."""
        source = SourceQuestion(prompt=question["prompt"], options=tuple(question["options"]))
        try:
            raw = self._translator.translate(source, locale)
            draft = parse_draft(raw)
        except DraftValidationError as exc:
            reason = f"rejected model output: {exc}"
        except Exception as exc:  # noqa: BLE001 - vendor boundary: one bad call must not abort the run
            reason = f"translator error: {type(exc).__name__}"
        else:
            self._store_draft(question, locale, draft, requested_by=requested_by)
            return None
        with _transaction(self._conn):
            self._log(
                question["set_id"],
                requested_by,
                "draft_failed",
                question_id=question["id"],
                locale=locale,
                source=SOURCE_AI,
                detail=reason,
            )
        return reason

    def _store_draft(
        self, question: dict[str, Any], locale: str, draft: TranslationDraft, *, requested_by: str
    ) -> None:
        with _transaction(self._conn):
            self._require_unlocked(question["set_id"])  # a lock may have landed mid-run
            existing = self._conn.execute(
                "SELECT id FROM translations WHERE question_id = ? AND locale = ?", (question["id"], locale)
            ).fetchone()
            options = json.dumps(list(draft.options))
            if existing is None:
                translation_id = _new_id()
                self._conn.execute(
                    "INSERT INTO translations"
                    " (id, question_id, locale, prompt, options, status, source, updated_by, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (translation_id, question["id"], locale, draft.prompt, options, STATUS_DRAFT, SOURCE_AI, requested_by, _now()),
                )
            else:
                translation_id = existing["id"]
                self._conn.execute(
                    "UPDATE translations SET prompt = ?, options = ?, status = ?, source = ?, updated_by = ?,"
                    " updated_at = ?, reviewed_by = NULL, reviewed_at = NULL, review_note = NULL,"
                    " version = version + 1 WHERE id = ?",
                    (draft.prompt, options, STATUS_DRAFT, SOURCE_AI, requested_by, _now(), translation_id),
                )
            self._log(
                question["set_id"],
                requested_by,
                "draft_created",
                question_id=question["id"],
                translation_id=translation_id,
                locale=locale,
                source=SOURCE_AI,
                detail=f"translator: {self._translator.name}",
            )

    # ----- review ----------------------------------------------------------

    def get_translation(self, translation_id: str) -> dict[str, Any]:
        return self._translation_row(translation_id)

    def edit_translation(
        self,
        translation_id: str,
        *,
        prompt: str,
        options: Sequence[str],
        edited_by: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        """A human rewrites the text. The result is a fresh draft that must be approved explicitly."""
        try:
            draft = parse_draft({"prompt": prompt, "options": list(options)})
        except DraftValidationError as exc:
            raise ValidationFailed(str(exc)) from exc
        with _transaction(self._conn):
            translation = self._translation_row(translation_id)
            set_id = self._question_row(translation["question_id"])["set_id"]
            self._require_unlocked(set_id)
            _check_version(translation, expected_version)
            self._conn.execute(
                "UPDATE translations SET prompt = ?, options = ?, status = ?, source = ?, updated_by = ?,"
                " updated_at = ?, reviewed_by = NULL, reviewed_at = NULL, review_note = NULL,"
                " version = version + 1 WHERE id = ?",
                (draft.prompt, json.dumps(list(draft.options)), STATUS_DRAFT, SOURCE_HUMAN, edited_by, _now(), translation_id),
            )
            self._log(
                set_id,
                edited_by,
                "translation_edited",
                question_id=translation["question_id"],
                translation_id=translation_id,
                locale=translation["locale"],
                source=SOURCE_HUMAN,
            )
        return self._translation_row(translation_id)

    def approve_translation(
        self, translation_id: str, *, reviewer: str, expected_version: int | None
    ) -> dict[str, Any]:
        return self._review(translation_id, STATUS_APPROVED, reviewer=reviewer, note=None, expected_version=expected_version)

    def reject_translation(
        self, translation_id: str, *, reviewer: str, note: str, expected_version: int | None
    ) -> dict[str, Any]:
        return self._review(translation_id, STATUS_REJECTED, reviewer=reviewer, note=note, expected_version=expected_version)

    def _review(
        self,
        translation_id: str,
        status: str,
        *,
        reviewer: str,
        note: str | None,
        expected_version: int | None,
    ) -> dict[str, Any]:
        with _transaction(self._conn):
            translation = self._translation_row(translation_id)
            set_id = self._question_row(translation["question_id"])["set_id"]
            self._require_unlocked(set_id)
            _check_version(translation, expected_version)
            # Belt and braces: nothing malformed can be approved even if it somehow got stored.
            try:
                parse_draft({"prompt": translation["prompt"], "options": translation["options"]})
            except DraftValidationError as exc:
                raise ValidationFailed(f"cannot approve: {exc}") from exc
            self._conn.execute(
                "UPDATE translations SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?,"
                " version = version + 1 WHERE id = ?",
                (status, reviewer, _now(), note, translation_id),
            )
            self._log(
                set_id,
                reviewer,
                f"translation_{status}",
                question_id=translation["question_id"],
                translation_id=translation_id,
                locale=translation["locale"],
                source=translation["source"],
                detail=note,
            )
        return self._translation_row(translation_id)


def _is_replaceable(existing: dict[str, Any], overwrite_drafts: bool) -> bool:
    """Machine output may replace machine output nobody has approved. Human text is never overwritten."""
    if not overwrite_drafts:
        return False
    return existing["source"] == SOURCE_AI and existing["status"] in (STATUS_DRAFT, STATUS_REJECTED)


def _check_version(translation: dict[str, Any], expected_version: int | None) -> None:
    if expected_version is not None and translation["version"] != expected_version:
        raise ConflictError(
            "this translation changed since you loaded it (someone else may be reviewing it); reload and try again"
        )
