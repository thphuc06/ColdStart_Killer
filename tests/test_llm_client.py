from __future__ import annotations

import builtins

import pytest

from src.llm_client import call_qwen
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


def test_call_qwen_raises_clear_error_when_ollama_package_missing(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ollama":
            raise ImportError("missing ollama")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="pip install ollama"):
        call_qwen("Translate this")

