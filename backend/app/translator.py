"""The translation boundary: the only place question text leaves the application.

A real generative model will eventually sit behind `Translator`. For now a
deterministic stand-in produces pseudo-localised drafts so the whole workflow
can be exercised without a vendor.

Two rules are enforced here regardless of which implementation is plugged in:

1. The translator only ever receives a `SourceQuestion`: the English prompt and
   its options. No reviewer names, no episode titles, no identifiers.
2. Whatever comes back is untrusted. `parse_draft` checks the shape (exactly
   four non-empty, distinct options; printable text; sane lengths) before
   anything is stored. The same check is applied to human edits, so every
   piece of text that reaches the database has passed through one validator.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

OPTION_COUNT = 4
MAX_PROMPT_LENGTH = 500
MAX_OPTION_LENGTH = 200


@dataclass(frozen=True)
class SourceQuestion:
    """Exactly what a translator is allowed to see."""

    prompt: str
    options: tuple[str, ...]


@dataclass(frozen=True)
class TranslationDraft:
    """A draft that has passed validation and is safe to store."""

    prompt: str
    options: tuple[str, ...]


class Translator(Protocol):
    """Anything that can draft a translation. Swap implementations via `build_translator`."""

    name: str

    def translate(self, question: SourceQuestion, target_locale: str) -> object:
        """Return the raw output. Callers must run it through `parse_draft`."""
        ...


class DraftValidationError(ValueError):
    """Raised when translator output (or a human edit) is not a usable draft."""


def _clean_text(value: object, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise DraftValidationError(f"{field} must be text")
    # Collapse all whitespace (including newlines) and drop control / zero-width characters.
    text = "".join(ch for ch in " ".join(value.split()) if ch.isprintable())
    if not text:
        raise DraftValidationError(f"{field} is empty")
    if len(text) > max_length:
        raise DraftValidationError(f"{field} is longer than {max_length} characters")
    return text


def parse_draft(raw: object) -> TranslationDraft:
    """Validate untrusted draft data. Raises DraftValidationError with a plain-English reason."""
    if not isinstance(raw, Mapping):
        raise DraftValidationError("draft must be an object with 'prompt' and 'options'")
    prompt = _clean_text(raw.get("prompt"), field="prompt", max_length=MAX_PROMPT_LENGTH)
    options = raw.get("options")
    if not isinstance(options, Sequence) or isinstance(options, str):
        raise DraftValidationError("options must be a list")
    if len(options) != OPTION_COUNT:
        raise DraftValidationError(f"expected {OPTION_COUNT} options, got {len(options)}")
    cleaned = tuple(
        _clean_text(option, field=f"option {index + 1}", max_length=MAX_OPTION_LENGTH)
        for index, option in enumerate(options)
    )
    if len({option.casefold() for option in cleaned}) != OPTION_COUNT:
        raise DraftValidationError("options must be distinct")
    return TranslationDraft(prompt=prompt, options=cleaned)


class PseudoTranslator:
    """Deterministic stand-in. Tags every string with the locale so drafts are visibly machine-made."""

    name = "pseudo-v1"

    def translate(self, question: SourceQuestion, target_locale: str) -> object:
        return {
            "prompt": f"[{target_locale}] {question.prompt}",
            "options": [f"[{target_locale}] {option}" for option in question.options],
        }


_TRANSLATORS: dict[str, type[PseudoTranslator]] = {
    "pseudo": PseudoTranslator,
}


def build_translator(name: str) -> Translator:
    """Resolve a translator by name (set `TLD_TRANSLATOR`). Unknown names fail loudly at startup."""
    if name not in _TRANSLATORS:
        raise ValueError(f"unknown translator {name!r}; choose from {sorted(_TRANSLATORS)}")
    return _TRANSLATORS[name]()
