"""HTTP layer. Thin: validation via pydantic, everything else delegated to `Desk`.

No `from __future__ import annotations` here: FastAPI must see the real `Depends` annotation,
not a string, for the locally defined `DeskDep` alias.
"""

import mimetypes
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.db import connect, init_schema
from app.schemas import (
    Actor,
    ApproveIn,
    CreateSetIn,
    DraftRequest,
    DraftRunResult,
    EventOut,
    LocaleInfo,
    LockIn,
    QuestionIn,
    QuestionOut,
    RejectIn,
    SetDetail,
    SetSummary,
    TranslationEditIn,
    TranslationOut,
)
from app.service import Desk, DomainError
from app.translator import Translator

# Locales offered in the UI. The API accepts any well-formed `xx-YY` code.
SUPPORTED_LOCALES = [
    LocaleInfo(code="es-ES", name="Spanish (Spain)"),
    LocaleInfo(code="es-MX", name="Spanish (Mexico)"),
    LocaleInfo(code="pt-BR", name="Portuguese (Brazil)"),
    LocaleInfo(code="fr-FR", name="French (France)"),
    LocaleInfo(code="de-DE", name="German (Germany)"),
    LocaleInfo(code="it-IT", name="Italian (Italy)"),
    LocaleInfo(code="nl-NL", name="Dutch (Netherlands)"),
    LocaleInfo(code="pl-PL", name="Polish (Poland)"),
    LocaleInfo(code="ja-JP", name="Japanese (Japan)"),
    LocaleInfo(code="ko-KR", name="Korean (Korea)"),
]


def create_app(
    *,
    db_path: Path,
    translator: Translator,
    cors_origins: Sequence[str] = (),
    frontend_dist: Path | None = None,
) -> FastAPI:
    init_schema(db_path)
    app = FastAPI(title="Trivia Localisation Desk API", version="0.1.0")
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["*"], allow_headers=["*"])

    def get_desk() -> Iterator[Desk]:
        conn = connect(db_path)
        try:
            yield Desk(conn, translator)
        finally:
            conn.close()

    DeskDep = Annotated[Desk, Depends(get_desk)]

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "translator": translator.name}

    @app.get("/api/locales", response_model=list[LocaleInfo])
    def list_locales() -> list[LocaleInfo]:
        return SUPPORTED_LOCALES

    # ----- sets --------------------------------------------------------------

    @app.get("/api/sets", response_model=list[SetSummary])
    def list_sets(desk: DeskDep) -> object:
        return desk.list_sets()

    @app.post("/api/sets", response_model=SetDetail, status_code=201)
    def create_set(body: CreateSetIn, desk: DeskDep) -> object:
        return desk.create_set(title=body.title, locales=body.locales, created_by=body.created_by)

    @app.get("/api/sets/{set_id}", response_model=SetDetail)
    def get_set(set_id: str, desk: DeskDep) -> object:
        return desk.get_set(set_id)

    @app.get("/api/sets/{set_id}/events", response_model=list[EventOut])
    def list_events(set_id: str, desk: DeskDep) -> object:
        return desk.list_events(set_id)

    @app.post("/api/sets/{set_id}/lock", response_model=SetDetail)
    def lock_set(set_id: str, body: LockIn, desk: DeskDep) -> object:
        return desk.lock_set(set_id, locked_by=body.locked_by)

    @app.post("/api/sets/{set_id}/drafts", response_model=DraftRunResult)
    def generate_drafts(set_id: str, body: DraftRequest, desk: DeskDep) -> object:
        return desk.generate_drafts(
            set_id, requested_by=body.requested_by, locales=body.locales, overwrite_drafts=body.overwrite_drafts
        )

    # ----- questions ---------------------------------------------------------

    @app.post("/api/sets/{set_id}/questions", response_model=QuestionOut, status_code=201)
    def add_question(set_id: str, body: QuestionIn, desk: DeskDep) -> object:
        return desk.add_question(
            set_id, prompt=body.prompt, options=body.options, correct_index=body.correct_index, author=body.author
        )

    @app.put("/api/questions/{question_id}", response_model=QuestionOut)
    def update_question(question_id: str, body: QuestionIn, desk: DeskDep) -> object:
        return desk.update_question(
            question_id, prompt=body.prompt, options=body.options, correct_index=body.correct_index, author=body.author
        )

    @app.delete("/api/questions/{question_id}", status_code=204)
    def delete_question(question_id: str, actor: Annotated[Actor, Query()], desk: DeskDep) -> Response:
        desk.delete_question(question_id, actor=actor)
        return Response(status_code=204)

    # ----- translations ------------------------------------------------------

    @app.put("/api/translations/{translation_id}", response_model=TranslationOut)
    def edit_translation(translation_id: str, body: TranslationEditIn, desk: DeskDep) -> object:
        return desk.edit_translation(
            translation_id,
            prompt=body.prompt,
            options=body.options,
            edited_by=body.edited_by,
            expected_version=body.expected_version,
        )

    @app.post("/api/translations/{translation_id}/approve", response_model=TranslationOut)
    def approve_translation(translation_id: str, body: ApproveIn, desk: DeskDep) -> object:
        return desk.approve_translation(translation_id, reviewer=body.reviewer, expected_version=body.expected_version)

    @app.post("/api/translations/{translation_id}/reject", response_model=TranslationOut)
    def reject_translation(translation_id: str, body: RejectIn, desk: DeskDep) -> object:
        return desk.reject_translation(
            translation_id, reviewer=body.reviewer, note=body.note, expected_version=body.expected_version
        )

    if frontend_dist is not None and frontend_dist.is_dir():
        _mount_frontend(app, frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app, falling back to index.html for client-side routes."""
    root = dist.resolve()
    # Windows can map .js to text/plain via the registry, which browsers refuse for module scripts.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
