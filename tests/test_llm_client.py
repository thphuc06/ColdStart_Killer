from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

import src.llm_client as llm_client
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


def test_call_qwen_includes_num_ctx_and_num_thread_when_configured(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(llm_client, "_ollama_chat", lambda: fake_chat)
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(
            ollama_model="qwen3:8b",
            ollama_num_ctx=32768,
            ollama_num_thread=12,
        ),
    )

    result = call_qwen("hello", max_tokens=321, temperature=0.1)

    assert result == "ok"
    assert captured["model"] == "qwen3:8b"
    assert captured["options"] == {
        "num_predict": 321,
        "temperature": 0.1,
        "num_ctx": 32768,
        "num_thread": 12,
    }

