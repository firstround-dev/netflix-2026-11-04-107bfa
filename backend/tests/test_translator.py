from __future__ import annotations

import pytest

from app.translator import DraftValidationError, PseudoTranslator, SourceQuestion, build_translator, parse_draft

GOOD = {"prompt": "¿Cuál es la capital de Francia?", "options": ["París", "Roma", "Madrid", "Berlín"]}


def test_valid_draft_passes_through_unchanged() -> None:
    draft = parse_draft(GOOD)
    assert draft.prompt == GOOD["prompt"]
    assert list(draft.options) == GOOD["options"]


def test_whitespace_and_control_characters_are_cleaned() -> None:
    draft = parse_draft({"prompt": "  ¿Qué\n\tes   esto?​ ", "options": ["a\x00", " b ", "c\n", "d"]})
    assert draft.prompt == "¿Qué es esto?"
    assert list(draft.options) == ["a", "b", "c", "d"]


def test_html_is_kept_as_text_not_rejected() -> None:
    # Shape is valid; escaping is the UI's job, and the linguist will see and fix it.
    draft = parse_draft({"prompt": "<script>alert(1)</script>", "options": ["a", "b", "c", "d"]})
    assert draft.prompt == "<script>alert(1)</script>"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("just a string", "must be an object"),
        (None, "must be an object"),
        ({"prompt": "x"}, "options must be a list"),
        ({"prompt": "x", "options": "a,b,c,d"}, "options must be a list"),
        ({"prompt": "x", "options": ["a", "b", "c"]}, "expected 4 options, got 3"),
        ({"prompt": "x", "options": ["a", "b", "c", "d", "e"]}, "expected 4 options, got 5"),
        ({"prompt": "", "options": ["a", "b", "c", "d"]}, "prompt is empty"),
        ({"prompt": "x", "options": ["a", "", "c", "d"]}, "option 2 is empty"),
        ({"prompt": "x", "options": ["a", 2, "c", "d"]}, "option 2 must be text"),
        ({"prompt": 5, "options": ["a", "b", "c", "d"]}, "prompt must be text"),
        ({"prompt": "x", "options": ["a", "A", "c", "d"]}, "options must be distinct"),
        ({"prompt": "x" * 501, "options": ["a", "b", "c", "d"]}, "longer than 500"),
        ({"prompt": "x", "options": ["a" * 201, "b", "c", "d"]}, "longer than 200"),
    ],
)
def test_malformed_drafts_are_rejected(raw: object, message: str) -> None:
    with pytest.raises(DraftValidationError, match=message):
        parse_draft(raw)


def test_pseudo_translator_output_is_valid_and_tagged() -> None:
    raw = PseudoTranslator().translate(SourceQuestion(prompt="Hello?", options=("a", "b", "c", "d")), "fr-FR")
    draft = parse_draft(raw)
    assert draft.prompt == "[fr-FR] Hello?"
    assert draft.options == ("[fr-FR] a", "[fr-FR] b", "[fr-FR] c", "[fr-FR] d")


def test_build_translator_rejects_unknown_names() -> None:
    assert build_translator("pseudo").name == "pseudo-v1"
    with pytest.raises(ValueError, match="unknown translator"):
        build_translator("gpt-whatever")
