from __future__ import annotations

import re
from typing import Any


UUID_LIKE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
GENERIC_INTEREST_LABELS = {"interest", "interests", "unknown", "product", "item"}
BLOCKED_EXACT_LABELS = {
    "bm25",
    "detail_similar",
    "item_item_cf",
    "profile_seed",
    "recommendation_log",
    "search_click",
    "semantic_neighbor",
    "vector",
}
SPEC_MARKERS = (
    "amoled",
    "bluetooth",
    "capacitive",
    "colors",
    "display",
    "dpi",
    "gb",
    "ghz",
    "hz",
    "inch",
    "mah",
    "megapixel",
    "mp",
    "oled",
    "ram",
    "resolution",
    "screen",
    "specification",
    "touchscreen",
    "usb",
    "wifi",
)


def _raw_string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def normalize_interest_label(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text.strip(" -_,.;:/|[](){}")


def is_generic_interest_label(value: Any) -> bool:
    label = normalize_interest_label(value).casefold()
    return label in GENERIC_INTEREST_LABELS


def is_uuid_like_label(value: Any) -> bool:
    label = normalize_interest_label(value)
    return bool(label and UUID_LIKE_RE.fullmatch(label))


def is_fact_like_label(value: Any, *, max_length: int) -> bool:
    label = normalize_interest_label(value)
    if not label:
        return False
    lower = label.casefold()
    digit_count = sum(character.isdigit() for character in label)
    punctuation_count = sum(character in ",;:.()/|" for character in label)
    word_count = len(lower.split())
    marker_hit = any(marker in lower for marker in SPEC_MARKERS)

    if len(label) > max_length:
        return True
    if marker_hit and (digit_count > 0 or punctuation_count > 0 or word_count >= 5):
        return True
    if digit_count >= 3 and punctuation_count >= 2:
        return True
    if word_count >= 10 and (digit_count > 0 or punctuation_count > 0):
        return True
    return False


def is_valid_interest_label(value: Any, *, max_length: int) -> bool:
    label = normalize_interest_label(value)
    if not label:
        return False
    if is_generic_interest_label(label):
        return False
    if label.casefold() in BLOCKED_EXACT_LABELS:
        return False
    if not any(character.isalpha() for character in label):
        return False
    if is_uuid_like_label(label):
        return False
    if is_fact_like_label(label, max_length=max_length):
        return False
    return True


def sanitize_interest_labels(
    value: Any,
    *,
    max_length: int,
    limit: int | None = None,
) -> tuple[list[str], int]:
    labels: list[str] = []
    invalid_count = 0
    seen: set[str] = set()
    for raw_value in _raw_string_values(value):
        label = normalize_interest_label(raw_value)
        if not label:
            continue
        if not is_valid_interest_label(label, max_length=max_length):
            invalid_count += 1
            continue
        dedupe_key = label.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        labels.append(label)
        if limit is not None and len(labels) >= limit:
            break
    return labels, invalid_count