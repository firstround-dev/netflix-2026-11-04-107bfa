"""Request and response models for the HTTP API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.translator import MAX_OPTION_LENGTH, MAX_PROMPT_LENGTH, OPTION_COUNT

# Names are self-reported (there is no auth yet) but they are always required and recorded.
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Locale = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z]{2,3}-[A-Z]{2}$")]
PromptText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_LENGTH)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_OPTION_LENGTH)]
Options = Annotated[list[OptionText], Field(min_length=OPTION_COUNT, max_length=OPTION_COUNT)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

TranslationStatus = Literal["draft", "approved", "rejected"]
TextSource = Literal["ai", "human"]
SetStatus = Literal["draft", "locked"]


def _distinct_options(options: list[str]) -> list[str]:
    if len({option.casefold() for option in options}) != len(options):
        raise ValueError("options must be distinct")
    return options


# ----- requests ------------------------------------------------------------


class CreateSetIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    locales: list[Locale] = Field(min_length=1)
    created_by: Actor


class QuestionIn(BaseModel):
    prompt: PromptText
    options: Options
    correct_index: int = Field(ge=0, le=OPTION_COUNT - 1)
    author: Actor

    @field_validator("options")
    @classmethod
    def _options_distinct(cls, options: list[str]) -> list[str]:
        return _distinct_options(options)


class DraftRequest(BaseModel):
    requested_by: Actor
    locales: list[Locale] | None = None
    overwrite_drafts: bool = False


class TranslationEditIn(BaseModel):
    prompt: PromptText
    options: Options
    edited_by: Actor
    expected_version: int | None = None


class ApproveIn(BaseModel):
    reviewer: Actor
    expected_version: int | None = None


class RejectIn(ApproveIn):
    note: Note


class LockIn(BaseModel):
    locked_by: Actor


# ----- responses -----------------------------------------------------------


class LocaleInfo(BaseModel):
    code: str
    name: str


class TranslationOut(BaseModel):
    id: str
    question_id: str
    locale: str
    prompt: str
    options: list[str]
    status: TranslationStatus
    source: TextSource
    updated_by: str
    updated_at: str
    reviewed_by: str | None
    reviewed_at: str | None
    review_note: str | None
    version: int


class QuestionOut(BaseModel):
    id: str
    set_id: str
    position: int
    prompt: str
    options: list[str]
    correct_index: int
    created_by: str
    updated_at: str
    translations: dict[str, TranslationOut]


class LocaleReadiness(BaseModel):
    total: int
    approved: int
    draft: int
    rejected: int
    missing: int


class Readiness(BaseModel):
    ready: bool
    blockers: list[str]
    per_locale: dict[str, LocaleReadiness]


class SetBase(BaseModel):
    id: str
    title: str
    locales: list[str]
    status: SetStatus
    created_by: str
    created_at: str
    locked_by: str | None
    locked_at: str | None


class SetSummary(SetBase):
    question_count: int
    ready: bool


class SetDetail(SetBase):
    questions: list[QuestionOut]
    readiness: Readiness


class DraftFailure(BaseModel):
    question_id: str
    locale: str
    reason: str


class DraftRunResult(BaseModel):
    created: int
    skipped: int
    failed: list[DraftFailure]


class EventOut(BaseModel):
    id: int
    set_id: str
    question_id: str | None
    translation_id: str | None
    locale: str | None
    actor: str
    action: str
    source: str | None
    detail: str | None
    at: str
