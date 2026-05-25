from __future__ import annotations

from typing import Any

from src.behavior.event_logger import log_clickstream_event
from src.config import Settings, get_settings
from src.utils import utc_now_iso


MAX_OPTION_SCAN = 500
DEFAULT_PRICE_BUCKETS = [
    {"id": "unknown", "label": "Open to any price"},
    {"id": "under_100k", "label": "Under 100k"},
    {"id": "100k_300k", "label": "100k to 300k"},
    {"id": "300k_500k", "label": "300k to 500k"},
    {"id": "500k_1m", "label": "500k to 1m"},
    {"id": "over_1m", "label": "Over 1m"},
]
DEFAULT_INTENT_CHIPS = [
    {"id": "daily_use", "label": "Daily use"},
    {"id": "gift_ready", "label": "Gift ready"},
    {"id": "budget_pick", "label": "Budget pick"},
    {"id": "premium_quality", "label": "Premium quality"},
    {"id": "beginner_friendly", "label": "Beginner friendly"},
    {"id": "highly_rated", "label": "Highly rated"},
]
FALLBACK_CATEGORIES = [
    {"id": "all_beauty", "label": "Beauty"},
    {"id": "all_electronics", "label": "Electronics"},
    {"id": "amazon_fashion", "label": "Fashion"},
    {"id": "home_and_kitchen", "label": "Home and kitchen"},
]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _unique_texts(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _display_label(value: str) -> str:
    text = value.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else value


def _cursor_to_list(cursor: Any, *, limit: int) -> list[dict[str, Any]]:
    if hasattr(cursor, "sort") and not isinstance(cursor, list):
        try:
            cursor = cursor.sort("quality_score", -1)
        except TypeError:
            cursor = cursor.sort([("quality_score", -1)])
    if hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)
    return [dict(doc) for doc in cursor][:limit]


def _load_catalog_snapshot(items_collection: Any, *, limit: int = MAX_OPTION_SCAN) -> list[dict[str, Any]]:
    projection = {
        "_id": 1,
        "item_id": 1,
        "title_en": 1,
        "title": 1,
        "brand": 1,
        "category_id": 1,
        "source_category": 1,
        "price_bucket": 1,
        "price_vnd": 1,
        "image_url": 1,
        "image_fallback_url": 1,
        "quality_score": 1,
    }
    return _cursor_to_list(items_collection.find({}, projection), limit=limit)


def _category_options(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for item in items:
        category_id = _clean_text(item.get("category_id"))
        if not category_id:
            continue
        counts[category_id] = counts.get(category_id, 0) + 1
        labels.setdefault(category_id, _clean_text(item.get("source_category")) or _display_label(category_id))
    return [
        {"id": category_id, "label": labels.get(category_id, _display_label(category_id)), "count": count}
        for category_id, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
    ]


def _seed_item_options(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    seed_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        item_id = _clean_text(item.get("item_id") or item.get("_id"))
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        seed_items.append(
            {
                "item_id": item_id,
                "title": _clean_text(item.get("title_en") or item.get("title") or item_id),
                "brand": _clean_text(item.get("brand")),
                "category_id": _clean_text(item.get("category_id")),
                "price_bucket": _clean_text(item.get("price_bucket") or "unknown"),
                "price_vnd": item.get("price_vnd"),
                "image_url": item.get("image_url") or item.get("image_fallback_url"),
            }
        )
        if len(seed_items) >= limit:
            break
    return seed_items


def get_onboarding_options(
    *,
    items_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.enable_onboarding:
        return {
            "ok": True,
            "enabled": False,
            "categories": [],
            "price_buckets": DEFAULT_PRICE_BUCKETS,
            "intent_chips": DEFAULT_INTENT_CHIPS,
            "seed_items": [],
            "source": "disabled",
            "message": "Onboarding is disabled by ENABLE_ONBOARDING=false.",
        }

    try:
        items = _load_catalog_snapshot(items_collection)
        categories = _category_options(items) or FALLBACK_CATEGORIES
        seed_items = _seed_item_options(items, limit=max(active_settings.onboarding_preview_limit, 1))
        source = "catalog_snapshot" if items else "fallback_options"
    except Exception as exc:
        categories = FALLBACK_CATEGORIES
        seed_items = []
        source = "fallback_options"
        return {
            "ok": True,
            "enabled": True,
            "categories": categories,
            "price_buckets": DEFAULT_PRICE_BUCKETS,
            "intent_chips": DEFAULT_INTENT_CHIPS,
            "seed_items": seed_items,
            "source": source,
            "warning": f"Catalog options unavailable; using generic fallback options: {exc}",
        }

    return {
        "ok": True,
        "enabled": True,
        "categories": categories,
        "price_buckets": DEFAULT_PRICE_BUCKETS,
        "intent_chips": DEFAULT_INTENT_CHIPS,
        "seed_items": seed_items,
        "source": source,
    }


def validate_onboarding_preferences(
    payload: dict[str, Any],
    *,
    options: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, list[str]]:
    active_settings = settings or get_settings()
    categories = _unique_texts(payload.get("selected_categories"))
    price_buckets = _unique_texts(payload.get("selected_price_buckets"))
    intents = _unique_texts(payload.get("selected_intents"))
    seed_item_ids = _unique_texts(payload.get("selected_seed_item_ids"))

    if len(seed_item_ids) > max(active_settings.onboarding_max_seed_items, 0):
        raise ValueError(f"selected_seed_item_ids may contain at most {active_settings.onboarding_max_seed_items} items")

    known_categories = {str(item.get("id")) for item in options.get("categories", []) if item.get("id")}
    known_prices = {str(item.get("id")) for item in options.get("price_buckets", []) if item.get("id")}
    known_intents = {str(item.get("id")) for item in options.get("intent_chips", []) if item.get("id")}
    known_seed_items = {str(item.get("item_id")) for item in options.get("seed_items", []) if item.get("item_id")}

    invalid_categories = sorted(set(categories) - known_categories) if known_categories else []
    invalid_prices = sorted(set(price_buckets) - known_prices) if known_prices else []
    invalid_intents = sorted(set(intents) - known_intents) if known_intents else []
    invalid_seed_items = sorted(set(seed_item_ids) - known_seed_items) if known_seed_items or seed_item_ids else []
    errors = []
    if invalid_categories:
        errors.append(f"unknown categories: {', '.join(invalid_categories)}")
    if invalid_prices:
        errors.append(f"unknown price buckets: {', '.join(invalid_prices)}")
    if invalid_intents:
        errors.append(f"unknown intents: {', '.join(invalid_intents)}")
    if invalid_seed_items:
        errors.append(f"unknown seed items: {', '.join(invalid_seed_items)}")
    if errors:
        raise ValueError("; ".join(errors))

    return {
        "selected_categories": categories,
        "selected_price_buckets": price_buckets,
        "selected_intents": intents,
        "selected_seed_item_ids": seed_item_ids,
    }


def preview_onboarding_preferences(
    payload: dict[str, Any],
    *,
    items_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    options = get_onboarding_options(items_collection=items_collection, settings=settings)
    if not options.get("enabled", True):
        return {"ok": True, "enabled": False, "write_performed": False, "preview": None, "message": options.get("message")}
    preferences = validate_onboarding_preferences(payload, options=options, settings=settings)
    seed_lookup = {item["item_id"]: item for item in options.get("seed_items", [])}
    selected_seed_items = [
        seed_lookup[item_id] for item_id in preferences["selected_seed_item_ids"] if item_id in seed_lookup
    ]
    summary_parts = []
    if preferences["selected_categories"]:
        summary_parts.append(f"{len(preferences['selected_categories'])} categories")
    if preferences["selected_price_buckets"]:
        summary_parts.append(f"{len(preferences['selected_price_buckets'])} price preferences")
    if preferences["selected_intents"]:
        summary_parts.append(f"{len(preferences['selected_intents'])} shopping intents")
    if selected_seed_items:
        summary_parts.append(f"{len(selected_seed_items)} seed items")
    summary = "Selected " + ", ".join(summary_parts) if summary_parts else "No preferences selected yet"
    return {
        "ok": True,
        "enabled": True,
        "write_performed": False,
        "preview": {
            **preferences,
            "seed_items": selected_seed_items,
            "summary": summary,
        },
        "explanation": "Preview only. These preferences become onboarding events after explicit completion.",
    }


def complete_onboarding(
    payload: dict[str, Any],
    *,
    users_collection: Any,
    clickstream_events_collection: Any,
    items_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    options = get_onboarding_options(items_collection=items_collection, settings=active_settings)
    if not options.get("enabled", True):
        return {"ok": False, "enabled": False, "write_performed": False, "message": options.get("message")}

    user_id_hash = _clean_text(payload.get("user_id_hash"))
    session_id = _clean_text(payload.get("session_id"))
    if not user_id_hash:
        raise ValueError("user_id_hash is required")
    if not session_id:
        raise ValueError("session_id is required")

    preferences = validate_onboarding_preferences(payload, options=options, settings=active_settings)
    now = utc_now_iso()
    onboarding_state = {
        "completed": True,
        "completed_at": now,
        **preferences,
    }
    update_result = users_collection.update_one(
        {"user_id_hash": user_id_hash},
        {"$set": {"onboarding": onboarding_state, "updated_at": now}},
    )
    matched_count = int(getattr(update_result, "matched_count", 0))
    if matched_count == 0:
        raise LookupError(f"user_id_hash not found: {user_id_hash}")

    event_results = []
    for item_id in preferences["selected_seed_item_ids"]:
        event_results.append(
            log_clickstream_event(
                user_id_hash=user_id_hash,
                session_id=session_id,
                item_id=item_id,
                event_type="wishlist",
                surface="onboarding",
                idempotency_key=f"onboarding:{user_id_hash}:{session_id}:{item_id}",
                client={"component": "onboarding-wizard", "device_type": "desktop"},
                metadata={
                    "source": "onboarding_v1",
                    "selected_categories": preferences["selected_categories"],
                    "selected_price_buckets": preferences["selected_price_buckets"],
                    "selected_intents": preferences["selected_intents"],
                },
                clickstream_events_collection=clickstream_events_collection,
            )
        )

    inserted_events = sum(1 for result in event_results if result.get("inserted"))
    return {
        "ok": True,
        "enabled": True,
        "write_performed": True,
        "user_id_hash": user_id_hash,
        "onboarding": onboarding_state,
        "events_attempted": len(event_results),
        "events_inserted": inserted_events,
        "event_results": event_results,
        "message": "Onboarding saved. Run behavior processing later to derive signals and profile updates.",
    }
