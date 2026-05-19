from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.normalize_amazon import (
    compute_tier,
    extract_image_urls,
    extract_primary_image_url,
    listify_text,
    normalize_record,
    parse_details,
    parse_price,
)


def test_listify_text_handles_list_string_and_dict() -> None:
    assert listify_text(["a", "b"]) == ["a", "b"]
    assert listify_text('["a", "b"]') == ["a", "b"]
    assert listify_text({"Color": "Red"}) == ["Color: Red"]


def test_parse_details_handles_json_and_plain_text() -> None:
    assert parse_details('{"Brand": "Acme"}') == {"Brand": "Acme"}
    assert parse_details("Brand: Acme") == {"raw": "Brand: Acme"}


def test_parse_price_statuses() -> None:
    assert parse_price("$12.34") == (12.34, "parsed")
    assert parse_price(None) == (None, "missing")
    assert parse_price("not available") == (None, "unparseable")


def test_image_url_extraction_varied_shapes() -> None:
    images = {
        "hi_res": ["https://example.com/a.jpg"],
        "large": [{"url": "https://example.com/b.jpg"}],
    }
    urls = extract_image_urls(images)
    assert "https://example.com/a.jpg" in urls
    assert "https://example.com/b.jpg" in urls
    assert extract_primary_image_url(images) == "https://example.com/a.jpg"


def test_quality_tier() -> None:
    assert compute_tier("Good title", 320, 12.0, "Store") == "tier_A"
    assert compute_tier("Good title", 180, 12.0, "Store") == "tier_B"
    assert compute_tier("Good title", 90, None, "") == "tier_C"


def test_normalize_record_builds_product_text_and_images() -> None:
    record = {
        "parent_asin": "B001",
        "title": "Gentle Cleanser",
        "store": "Acme",
        "main_category": "All Beauty",
        "categories": ["All Beauty"],
        "price": "$12.00",
        "description": ["A gentle cleanser for daily use."],
        "features": ["Fragrance free", "For sensitive skin"],
        "details": {"Brand": "Acme", "Size": "200 ml"},
        "images": {"large": ["https://example.com/cleanser.jpg"]},
    }
    row = normalize_record(record, "All_Beauty")
    assert row["parent_asin"] == "B001"
    assert row["primary_image_url"] == "https://example.com/cleanser.jpg"
    assert "Title: Gentle Cleanser" in row["product_text_for_llm"]
    assert row["description_text"]
    assert row["features_text"]
    assert row["details_text"]

