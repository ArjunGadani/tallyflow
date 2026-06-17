"""LLMs wrap JSON in fences or prose. parse_json_object must recover the object
or raise (so the repair-retry can fire)."""
import pytest

from backend.jsonutil import parse_json_object


def test_plain_json():
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_embedded_in_prose():
    text = 'Here is the result:\n{"doc_type": "invoice", "total": "10"}\nThanks!'
    assert parse_json_object(text)["doc_type"] == "invoice"


def test_unparseable_raises():
    with pytest.raises(ValueError):
        parse_json_object("no json here at all")
