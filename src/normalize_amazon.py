from __future__ import annotations

import ast
import json
import math
import re
import unicodedata
import warnings
from typing import Any


USD_TO_VND = 25_000


def is_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "none", "nan", "null"}:
        return True
    return False


def clean_string(value: Any) -> str:
    if is_null(value):
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_sequence_string(value: str) -> Any:
    text = value.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text[0] not in {"[", "{", "(", "'", '"'}:
        return value
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return value


def listify_text(value: Any) -> list[str]:
    if is_null(value):
        return []
    if isinstance(value, str):
        parsed = _parse_sequence_string(value)
        if parsed is value:
            return [clean_string(value)] if clean_string(value) else []
        return listify_text(parsed)
    if isinstance(value, dict):
        texts: list[str] = []
        for key, val in value.items():
            if is_null(val):
                continue
            if isinstance(val, (list, tuple, set)):
                texts.extend(listify_text(val))
            else:
                piece = clean_string(val)
                if piece:
                    texts.append(f"{clean_string(key)}: {piece}" if clean_string(key) else piece)
        return texts
    if isinstance(value, (list, tuple, set)):
        texts = []
        for item in value:
            if isinstance(item, (list, tuple, set, dict)):
                texts.extend(listify_text(item))
            else:
                text = clean_string(item)
                if text:
                    texts.append(text)
        return texts
    text = clean_string(value)
    return [text] if text else []


def join_text_list(value: Any) -> str:
    return "\n".join(listify_text(value))


def word_count(text: Any) -> int:
    cleaned = clean_string(text)
    if not cleaned:
        return 0
    return len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", cleaned))


def parse_details(value: Any) -> Any:
    if is_null(value):
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = _parse_sequence_string(value)
        if parsed is value:
            return {"raw": clean_string(value)} if clean_string(value) else {}
        return parsed
    return {"raw": clean_string(value)}


def details_to_text(details: Any) -> str:
    parsed = parse_details(details)
    if isinstance(parsed, dict):
        parts = []
        for key, value in parsed.items():
            if is_null(value):
                continue
            if isinstance(value, (dict, list, tuple, set)):
                text = join_text_list(value)
            else:
                text = clean_string(value)
            if text:
                parts.append(f"{clean_string(key)}: {text}")
        return "\n".join(parts)
    return join_text_list(parsed)


def parse_price(value: Any) -> tuple[float | None, str]:
    if is_null(value):
        return None, "missing"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        price = float(value)
        return (price, "parsed") if price > 0 else (None, "missing")
    text = clean_string(value)
    if not text:
        return None, "missing"
    text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None, "unparseable"
    try:
        price = float(match.group(1))
    except ValueError:
        return None, "unparseable"
    return (price, "parsed") if price > 0 else (None, "missing")


def parse_int(value: Any) -> int | None:
    if is_null(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and not math.isnan(value):
        return int(value)
    text = clean_string(value).replace(",", "")
    match = re.search(r"-?\d+", text)
    return int(match.group(0)) if match else None


def has_non_empty_sequence(value: Any) -> bool:
    return sequence_len(value) > 0


def sequence_len(value: Any) -> int:
    if is_null(value):
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    parsed = _parse_sequence_string(str(value)) if isinstance(value, str) else value
    if isinstance(parsed, (list, tuple, set, dict)):
        return len(parsed)
    return 1 if clean_string(value) else 0


def _collect_urls(value: Any, urls: list[str]) -> None:
    if is_null(value):
        return
    if isinstance(value, dict):
        for nested in value.values():
            _collect_urls(nested, urls)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            _collect_urls(nested, urls)
        return
    if isinstance(value, str):
        parsed = _parse_sequence_string(value)
        if parsed is not value:
            _collect_urls(parsed, urls)
            return
        for match in re.findall(r"https?://[^\s'\"<>]+", value):
            urls.append(match.rstrip("),]"))


def extract_image_urls(images: Any) -> list[str]:
    urls: list[str] = []
    _collect_urls(images, urls)
    seen: set[str] = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def extract_primary_image_url(images: Any) -> str | None:
    urls = extract_image_urls(images)
    if not urls:
        return None
    preferred = [url for url in urls if any(token in url.lower() for token in ("hi_res", "large", "images"))]
    return (preferred or urls)[0]


def extract_brand(details: Any, store: Any) -> tuple[str | None, str]:
    parsed = parse_details(details)
    if isinstance(parsed, dict):
        for key in ("Brand", "brand", "Manufacturer", "manufacturer"):
            brand = clean_string(parsed.get(key))
            if brand:
                source = "details.Brand" if "brand" in key.lower() else "details.Manufacturer"
                return brand, source
    store_text = clean_string(store)
    if store_text:
        return store_text, "store_fallback"
    return None, "none"


def slugify_category(value: Any) -> str:
    text = clean_string(value).lower()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def make_price_bucket(price_vnd: Any) -> str:
    if price_vnd is None:
        return "unknown"
    try:
        price = float(price_vnd)
    except (TypeError, ValueError):
        return "unknown"
    if price <= 0:
        return "unknown"
    if price < 100_000:
        return "under_100k"
    if price < 300_000:
        return "100k_300k"
    if price < 500_000:
        return "300k_500k"
    if price < 1_000_000:
        return "500k_1m"
    if price < 3_000_000:
        return "1m_3m"
    return "over_3m"


def content_richness_score(
    title_words: int,
    description_words: int,
    features_words: int,
    details_words: int,
    has_price: bool,
    has_images: bool,
    store_present: bool,
) -> float:
    combined_words = description_words + features_words + details_words
    score = min((title_words + combined_words) / 350, 1.0) * 0.45
    score += min(description_words / 120, 1.0) * 0.20
    score += min(features_words / 80, 1.0) * 0.15
    score += min(details_words / 80, 1.0) * 0.08
    score += 0.05 if has_price else 0.0
    score += 0.04 if has_images else 0.0
    score += 0.03 if store_present else 0.0
    return round(min(score, 1.0), 6)


def compute_tier(title: Any, combined_words: int, price_usd: float | None, store: Any) -> str:
    has_required = bool(clean_string(title)) and bool(clean_string(store)) and price_usd is not None and price_usd > 0
    if has_required and combined_words >= 300:
        return "tier_A"
    if has_required and combined_words >= 150:
        return "tier_B"
    if clean_string(title) and combined_words >= 80:
        return "tier_C"
    return "tier_D"


def enrichment_bucket(row: dict[str, Any]) -> str:
    missing = set(filter(None, clean_string(row.get("missing_fields", "")).split(",")))
    if not row.get("needs_enrichment"):
        return "not_needed"
    if {"description", "features"}.issubset(missing):
        return "missing_description_and_features"
    if "description" in missing:
        return "missing_description"
    if "features" in missing:
        return "missing_features"
    return "low_richness"


def missing_fields_for_row(row: dict[str, Any]) -> str:
    checks = {
        "title": row.get("title_present"),
        "store": row.get("store_present"),
        "main_category": row.get("categories_present"),
        "description": row.get("description_present"),
        "features": row.get("features_present"),
        "details": row.get("details_present"),
        "price": row.get("price_usd") is not None,
        "image": row.get("has_images"),
    }
    return ",".join(name for name, present in checks.items() if not present)


def _category_path(record: dict[str, Any], fallback: str) -> list[str]:
    raw = record.get("categories")
    if is_null(raw):
        raw = record.get("category")
    values = listify_text(raw)
    if not values:
        main = clean_string(record.get("main_category"))
        return [main] if main else [fallback]
    return values


def build_product_text_for_llm(
    title: str,
    brand: str | None,
    main_category: str,
    price_vnd: int | None,
    features_text: str,
    description_text: str,
    details_text: str,
) -> str:
    price_text = f"{price_vnd} VND" if price_vnd is not None else "unknown"
    return (
        f"Title: {title}\n"
        f"Brand: {brand or ''}\n"
        f"Category: {main_category}\n"
        f"Price: {price_text}\n\n"
        f"Features:\n{features_text}\n\n"
        f"Description:\n{description_text}\n\n"
        f"Details:\n{details_text}"
    ).strip()


def normalize_record(record: dict[str, Any], category_key: str) -> dict[str, Any]:
    title = clean_string(record.get("title"))
    store = clean_string(record.get("store"))
    details = parse_details(record.get("details"))
    description_text = join_text_list(record.get("description"))
    features_text = join_text_list(record.get("features"))
    details_text = details_to_text(details)
    category_path = _category_path(record, category_key)
    main_category = clean_string(record.get("main_category")) or category_path[0] or category_key
    category_id = slugify_category(main_category)
    price_usd, price_parse_status = parse_price(record.get("price"))
    price_vnd = int(round(price_usd * USD_TO_VND)) if price_usd is not None else None
    image_urls = extract_image_urls(record.get("images"))
    primary_image_url = extract_primary_image_url(record.get("images"))
    brand_candidate, brand_source = extract_brand(details, store)

    title_words = word_count(title)
    description_words = word_count(description_text)
    features_words = word_count(features_text)
    details_words = word_count(details_text)
    combined_words = description_words + features_words + details_words
    has_images = len(image_urls) > 0
    store_present = bool(store)
    content_richness = content_richness_score(
        title_words,
        description_words,
        features_words,
        details_words,
        price_usd is not None,
        has_images,
        store_present,
    )
    quality_tier = compute_tier(title, combined_words, price_usd, store)
    needs_enrichment = content_richness < 0.60 or description_words == 0 or features_words == 0
    enrichment_reason_parts = []
    if content_richness < 0.60:
        enrichment_reason_parts.append("low_content_richness")
    if description_words == 0:
        enrichment_reason_parts.append("missing_description")
    if features_words == 0:
        enrichment_reason_parts.append("missing_features")

    product_text_for_llm = build_product_text_for_llm(
        title=title,
        brand=brand_candidate,
        main_category=main_category,
        price_vnd=price_vnd,
        features_text=features_text,
        description_text=description_text,
        details_text=details_text,
    )
    row = {
        "category_key": category_key,
        "source_category": category_key,
        "parent_asin": clean_string(record.get("parent_asin")),
        "title": title,
        "store": store,
        "brand_candidate": brand_candidate,
        "brand_source": brand_source,
        "main_category": main_category,
        "category_id": category_id,
        "category_path": category_path,
        "categories_raw": record.get("categories"),
        "title_words": title_words,
        "description_words": description_words,
        "features_words": features_words,
        "details_words": details_words,
        "combined_words": combined_words,
        "price_usd": price_usd,
        "price_vnd": price_vnd,
        "price_parse_status": price_parse_status,
        "price_bucket": make_price_bucket(price_vnd),
        "has_images": has_images,
        "images_count": len(image_urls),
        "image_urls": image_urls,
        "primary_image_url": primary_image_url,
        "has_bought_together": has_non_empty_sequence(record.get("bought_together")),
        "title_present": bool(title),
        "description_present": description_words > 0,
        "features_present": features_words > 0,
        "details_present": details_words > 0,
        "store_present": store_present,
        "categories_present": bool(main_category),
        "quality_tier": quality_tier,
        "needs_enrichment": needs_enrichment,
        "enrichment_reason": ",".join(enrichment_reason_parts) if enrichment_reason_parts else "",
        "content_richness": content_richness,
        "rating_number": parse_int(record.get("rating_number")),
        "average_rating": record.get("average_rating"),
        "description_text": description_text,
        "features_text": features_text,
        "details_text": details_text,
        "product_text_for_llm": product_text_for_llm,
    }
    row["missing_fields"] = missing_fields_for_row(row)
    row["enrichment_bucket"] = enrichment_bucket(row)
    return row

