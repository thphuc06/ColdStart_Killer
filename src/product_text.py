from __future__ import annotations

from typing import Any

from .normalize_amazon import build_product_text_for_llm, clean_string, details_to_text, join_text_list, word_count


def build_product_text_from_parts(
    title: str,
    brand: str | None,
    category: str,
    price_vnd: int | None,
    features: list[str] | str,
    description: str,
    details: dict[str, Any] | str,
) -> str:
    return build_product_text_for_llm(
        title=clean_string(title),
        brand=clean_string(brand),
        main_category=clean_string(category),
        price_vnd=price_vnd,
        features_text=join_text_list(features),
        description_text=clean_string(description),
        details_text=details_to_text(details),
    )


def product_text_word_count(product_text_for_llm: str) -> int:
    return word_count(product_text_for_llm)

