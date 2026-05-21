from __future__ import annotations

from src.llm_client import extract_json_from_text


def test_extract_json_salvages_valid_objects_from_malformed_array() -> None:
    text = """[
      {"raw_text": "first", "confidence": 0.9},
      {"raw_text": "second", "confidence": 0.8},
      {"raw,"text": "broken", "confidence": 0.7}
    ]"""

    parsed = extract_json_from_text(text)

    assert isinstance(parsed, list)
    assert [item["raw_text"] for item in parsed] == ["first", "second"]

