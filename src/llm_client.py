from __future__ import annotations

import json
import logging
import re
from typing import Any

from ollama import chat

from .config import get_settings


logger = logging.getLogger(__name__)


def call_qwen(prompt: str, max_tokens: int = 800, temperature: float = 0.2) -> str:
    settings = get_settings()
    response = chat(
        model=settings.ollama_model,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": max_tokens, "temperature": temperature},
        think=False,
    )
    message = response.get("message", {}) if isinstance(response, dict) else getattr(response, "message", {})
    if isinstance(message, dict):
        return message.get("content", "")
    if hasattr(message, "content"):
        return str(message.content)
    return str(message)


def _strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _balanced_json_block(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _valid_object_blocks(text: str) -> list[dict]:
    objects = []
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start == -1:
            break
        block = _balanced_json_block(text[start:], "{", "}")
        if not block:
            idx = start + 1
            continue
        try:
            objects.append(json.loads(block))
        except json.JSONDecodeError:
            pass
        idx = start + len(block)
    return objects


def extract_json_from_text(text: str) -> dict | list | None:
    cleaned = _strip_markdown_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    list_start = cleaned.find("[")
    object_start = cleaned.find("{")
    if list_start != -1 and (object_start == -1 or list_start < object_start):
        list_block = _balanced_json_block(cleaned[list_start:], "[", "]")
        if list_block:
            try:
                return json.loads(list_block)
            except json.JSONDecodeError:
                objects = _valid_object_blocks(list_block)
                if objects:
                    return objects
        objects = _valid_object_blocks(cleaned[list_start:])
        if objects:
            return objects

    starts = [(cleaned.find("{"), "{", "}"), (cleaned.find("["), "[", "]")]
    candidates = [
        _balanced_json_block(cleaned, opener, closer)
        for _, opener, closer in sorted((item for item in starts if item[0] != -1), key=lambda item: item[0])
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    objects = _valid_object_blocks(cleaned)
    if objects:
        return objects

    logger.warning("Could not extract valid JSON from LLM output")
    return None


def expect_list_json(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "propositions", "hype_queries", "queries"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
