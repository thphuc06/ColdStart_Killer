from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

import numpy as np
from pymongo import UpdateOne

from src.behavior.event_logger import log_clickstream_event, log_recommendation_snapshot
from src.recommendation.schemas import EMBEDDING_DIM, SyntheticPersonaDocument
from src.schemas import to_mongo_dict


DEFAULT_SYNTHETIC_USERS = 40
DEFAULT_REQUESTS_PER_USER = 3
DEFAULT_ITEMS_PER_REQUEST = 10
DEFAULT_SEED = 42
DEFAULT_ANCHOR_ITEMS_PER_PERSONA = 8


@dataclass(frozen=True)
class SyntheticCandidate:
    item_id: str
    title: str
    brand: str
    category_id: str
    price_bucket: str
    price_vnd: int | None
    image_url: str | None
    quality_score: float
    item_semantic_embedding: list[float] | None
    top_aspects: list[str]
    num_hype_units: int


def default_personas() -> list[dict[str, Any]]:
    return [
        {
            "persona_id": "p_budget_skincare",
            "label": "Budget skincare shopper",
            "preferred_categories": {"all_beauty": 0.95, "amazon_fashion": 0.15},
            "preferred_price_buckets": {"under_100k": 0.80, "100k_300k": 0.95, "300k_500k": 0.35},
            "intent_keywords": ["oil control", "sensitive skin", "lightweight", "cleanser", "moisturizer"],
            "negative_keywords": ["expensive", "heavy texture"],
        },
        {
            "persona_id": "p_premium_skincare",
            "label": "Premium skincare shopper",
            "preferred_categories": {"all_beauty": 1.00},
            "preferred_price_buckets": {"500k_1m": 0.70, "1m_3m": 0.95, "over_3m": 0.65},
            "intent_keywords": ["serum", "anti aging", "premium", "treatment", "spf"],
            "negative_keywords": ["cheap packaging"],
        },
        {
            "persona_id": "p_makeup_gift",
            "label": "Makeup and beauty gift shopper",
            "preferred_categories": {"all_beauty": 0.80, "amazon_fashion": 0.45},
            "preferred_price_buckets": {"100k_300k": 0.55, "300k_500k": 0.90, "500k_1m": 0.65},
            "intent_keywords": ["gift", "makeup", "style", "set", "occasion"],
            "negative_keywords": ["industrial"],
        },
        {
            "persona_id": "p_phone_case",
            "label": "Phone case and protection shopper",
            "preferred_categories": {"cell_phones_and_accessories": 1.00, "all_electronics": 0.35},
            "preferred_price_buckets": {"under_100k": 0.50, "100k_300k": 0.95, "300k_500k": 0.45},
            "intent_keywords": ["phone case", "protection", "iphone", "samsung", "cover"],
            "negative_keywords": ["skin cream"],
        },
        {
            "persona_id": "p_charger_cable",
            "label": "Fast charger and cable shopper",
            "preferred_categories": {
                "cell_phones_and_accessories": 0.90,
                "all_electronics": 0.75,
                "computers": 0.35,
            },
            "preferred_price_buckets": {"100k_300k": 0.70, "300k_500k": 0.95, "500k_1m": 0.45},
            "intent_keywords": ["usb c", "fast charging", "cable", "charger", "adapter"],
            "negative_keywords": ["makeup"],
        },
        {
            "persona_id": "p_wireless_audio",
            "label": "Wireless audio accessory shopper",
            "preferred_categories": {
                "cell_phones_and_accessories": 0.70,
                "all_electronics": 0.90,
                "portable_audio_and_accessories": 1.00,
            },
            "preferred_price_buckets": {"300k_500k": 0.65, "500k_1m": 0.95, "1m_3m": 0.50},
            "intent_keywords": ["wireless", "earbuds", "headphones", "bluetooth", "audio"],
            "negative_keywords": ["cleanser"],
        },
        {
            "persona_id": "p_budget_cross_category",
            "label": "Budget shopper across categories",
            "preferred_categories": {
                "all_beauty": 0.55,
                "cell_phones_and_accessories": 0.70,
                "all_electronics": 0.50,
                "amazon_fashion": 0.45,
            },
            "preferred_price_buckets": {"under_100k": 0.80, "100k_300k": 1.00, "300k_500k": 0.35},
            "intent_keywords": ["budget", "useful", "daily", "gift", "portable"],
            "negative_keywords": ["overpriced"],
        },
        {
            "persona_id": "p_mixed_explorer",
            "label": "Mixed gift and exploration shopper",
            "preferred_categories": {
                "all_beauty": 0.55,
                "cell_phones_and_accessories": 0.55,
                "all_electronics": 0.45,
                "amazon_fashion": 0.45,
            },
            "preferred_price_buckets": {
                "100k_300k": 0.65,
                "300k_500k": 0.75,
                "500k_1m": 0.55,
                "1m_3m": 0.25,
            },
            "intent_keywords": ["gift", "explore", "interesting", "daily use", "style"],
            "negative_keywords": [],
        },
    ]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _embedding_array(value: Any) -> np.ndarray | None:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        return None
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all():
        return None
    return vector


def normalize_vector(vector: np.ndarray) -> list[float] | None:
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        return None
    return (vector / norm).astype(float).tolist()


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float | None:
    left_vector = _embedding_array(left)
    right_vector = _embedding_array(right)
    if left_vector is None or right_vector is None:
        return None
    denom = float(np.linalg.norm(left_vector) * np.linalg.norm(right_vector))
    if denom <= 0 or not math.isfinite(denom):
        return None
    return float(np.dot(left_vector, right_vector) / denom)


def fallback_persona_item_match(persona: dict[str, Any], item: SyntheticCandidate | dict[str, Any]) -> float:
    category = item.category_id if isinstance(item, SyntheticCandidate) else str(item.get("category_id", ""))
    price_bucket = item.price_bucket if isinstance(item, SyntheticCandidate) else str(item.get("price_bucket", ""))
    category_score = _safe_float(persona.get("preferred_categories", {}).get(category), 0.0)
    price_score = _safe_float(persona.get("preferred_price_buckets", {}).get(price_bucket), 0.0)
    return max(0.0, min(1.0, 0.60 * category_score + 0.40 * price_score))


def compute_persona_item_match(persona: dict[str, Any], item: SyntheticCandidate) -> float:
    category_score = _safe_float(persona.get("preferred_categories", {}).get(item.category_id), 0.0)
    price_score = _safe_float(persona.get("preferred_price_buckets", {}).get(item.price_bucket), 0.0)
    semantic = cosine_similarity(persona.get("intent_embedding"), item.item_semantic_embedding)
    if semantic is None:
        return fallback_persona_item_match(persona, item)
    semantic_score = (semantic + 1.0) / 2.0
    return max(0.0, min(1.0, 0.40 * category_score + 0.20 * price_score + 0.40 * semantic_score))


def simulate_click_probability(match_score: float, rank_position: int) -> float:
    position_bias = 1.0 / (1.0 + 0.08 * (max(rank_position, 1) - 1))
    base_prob = 1.0 / (1.0 + math.exp(-8.0 * (match_score - 0.5)))
    return max(0.0, min(0.95, base_prob * position_bias))


def cart_probability(match_score: float, clicked: bool) -> float:
    if not clicked:
        return 0.0
    return max(0.0, min(0.70, (match_score - 0.65) * 2.0))


def purchase_probability(cart_prob: float) -> float:
    return max(0.0, min(0.25, cart_prob * 0.28))


def candidate_from_docs(item: dict[str, Any], profile: dict[str, Any] | None) -> SyntheticCandidate:
    profile = profile or {}
    return SyntheticCandidate(
        item_id=str(item.get("_id") or item.get("item_id") or ""),
        title=str(item.get("title_en") or item.get("title") or ""),
        brand=str(item.get("brand") or ""),
        category_id=str(item.get("category_id") or profile.get("category_id") or ""),
        price_bucket=str(item.get("price_bucket") or profile.get("price_bucket") or "unknown"),
        price_vnd=_safe_int(item.get("price_vnd")),
        image_url=item.get("image_url"),
        quality_score=_safe_float(item.get("quality_score"), 0.0),
        item_semantic_embedding=profile.get("item_semantic_embedding"),
        top_aspects=[str(value) for value in profile.get("top_aspects", [])],
        num_hype_units=int(profile.get("num_hype_units") or 0),
    )


def load_candidates_from_collections(
    *,
    items_collection: Any,
    item_hype_profiles_collection: Any,
    limit: int | None = None,
) -> list[SyntheticCandidate]:
    profiles = {
        doc.get("item_id") or doc.get("_id"): doc
        for doc in item_hype_profiles_collection.find(
            {},
            {
                "_id": 1,
                "item_id": 1,
                "item_semantic_embedding": 1,
                "top_aspects": 1,
                "num_hype_units": 1,
                "category_id": 1,
                "price_bucket": 1,
            },
        )
    }
    projection = {
        "_id": 1,
        "title_en": 1,
        "brand": 1,
        "category_id": 1,
        "price_bucket": 1,
        "price_vnd": 1,
        "image_url": 1,
        "quality_score": 1,
    }
    cursor = items_collection.find({}, projection)
    if limit is not None and hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)

    candidates = []
    for item in cursor:
        item_id = item.get("_id")
        profile = profiles.get(item_id)
        if not item_id or profile is None:
            continue
        candidate = candidate_from_docs(item, profile)
        if candidate.item_id:
            candidates.append(candidate)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def build_persona_intent_embedding(
    persona: dict[str, Any],
    candidates: list[SyntheticCandidate],
    *,
    top_n: int = 80,
) -> list[float] | None:
    scored = []
    for candidate in candidates:
        vector = _embedding_array(candidate.item_semantic_embedding)
        if vector is None:
            continue
        score = fallback_persona_item_match(persona, candidate)
        if score > 0:
            scored.append((score, vector))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = scored[:top_n]
    weights = np.asarray([score for score, _ in selected], dtype=np.float64)
    vectors = np.vstack([vector for _, vector in selected])
    return normalize_vector(np.average(vectors, axis=0, weights=weights))


def prepare_personas(candidates: list[SyntheticCandidate]) -> list[dict[str, Any]]:
    personas = []
    for persona in default_personas():
        prepared = dict(persona)
        prepared["intent_embedding"] = build_persona_intent_embedding(prepared, candidates)
        personas.append(prepared)
    return personas


def persona_query(persona: dict[str, Any]) -> str:
    keywords = persona.get("intent_keywords") or [persona["label"]]
    return " ".join(str(keyword) for keyword in keywords[:3])


def _candidate_item_payload(
    candidate: SyntheticCandidate,
    *,
    rank_position: int,
    final_score: float,
    match_score: float,
    candidate_sources: list[str],
) -> dict[str, Any]:
    return {
        "item_id": candidate.item_id,
        "title": candidate.title,
        "brand": candidate.brand,
        "rank_position": rank_position,
        "final_score": final_score,
        "scores": {
            "profile_score": match_score,
            "semantic_neighbor_score": 0.0,
            "item_item_cf_score": 0.0,
            "category_affinity_score": match_score,
            "price_affinity_score": match_score,
            "exploration_score": max(0.0, 1.0 - match_score),
            "final_score": final_score,
        },
        "attribution": {
            "matched_unit_ids": [],
            "matched_intents": candidate.top_aspects,
            "matched_facts": [],
            "matched_channels": ["synthetic_persona_match"],
            "candidate_sources": candidate_sources,
            "matched_profile_interest_ids": [],
            "cf_evidence": None,
            "explanation": "Synthetic persona behavior seed for recommendation pipeline validation.",
        },
    }


def _rank_candidates_for_persona(
    persona: dict[str, Any],
    candidates: list[SyntheticCandidate],
    rng: random.Random,
) -> list[tuple[SyntheticCandidate, float]]:
    scored = []
    for candidate in candidates:
        match = compute_persona_item_match(persona, candidate)
        noise = rng.uniform(-0.06, 0.06)
        quality = 0.05 * candidate.quality_score
        scored.append((candidate, max(0.0, min(1.0, match + noise + quality))))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _choose_request_items(
    *,
    ranked: list[tuple[SyntheticCandidate, float]],
    anchors: list[SyntheticCandidate],
    global_anchors: list[SyntheticCandidate],
    rng: random.Random,
    request_index: int,
    items_per_request: int,
) -> list[tuple[SyntheticCandidate, float, list[str]]]:
    selected: dict[str, tuple[SyntheticCandidate, float, list[str]]] = {}
    if global_anchors:
        shared = global_anchors[request_index % len(global_anchors)]
        score = next((value for candidate, value in ranked if candidate.item_id == shared.item_id), 0.55)
        selected.setdefault(shared.item_id, (shared, score, ["cross_persona_anchor", "exploration"]))

    anchor_quota = min(3, items_per_request // 3)
    for anchor in anchors[request_index % max(len(anchors), 1):] + anchors[: request_index % max(len(anchors), 1)]:
        score = next((value for candidate, value in ranked if candidate.item_id == anchor.item_id), 0.65)
        selected.setdefault(anchor.item_id, (anchor, score, ["persona_anchor", "profile_seed"]))
        if len(selected) >= anchor_quota:
            break

    top_pool = ranked[: min(len(ranked), 80)]
    exploration_pool = ranked[min(len(ranked), 80): min(len(ranked), 240)] or ranked
    while len(selected) < items_per_request and top_pool:
        candidate, score = rng.choice(top_pool)
        selected.setdefault(candidate.item_id, (candidate, score, ["persona_match"]))
        if len(selected) >= items_per_request:
            break
        if len(selected) > len(top_pool):
            break

    while len(selected) < items_per_request and exploration_pool:
        candidate, score = rng.choice(exploration_pool)
        selected.setdefault(candidate.item_id, (candidate, score, ["exploration"]))
        if len(selected) > len(exploration_pool):
            break

    result = list(selected.values())[:items_per_request]
    result.sort(key=lambda item: item[1], reverse=True)
    return result


def _event_id(seed: int, user_index: int, request_index: int, item_id: str, event_type: str, extra: int = 0) -> str:
    safe_item = "".join(ch if ch.isalnum() else "_" for ch in item_id)[-16:]
    return f"evt_syn_{seed}_{user_index:03d}_{request_index:02d}_{safe_item}_{event_type}_{extra}"


def build_synthetic_behavior_plan(
    *,
    candidates: list[SyntheticCandidate],
    users: int = DEFAULT_SYNTHETIC_USERS,
    requests_per_user: int = DEFAULT_REQUESTS_PER_USER,
    items_per_request: int = DEFAULT_ITEMS_PER_REQUEST,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    if users <= 0:
        raise ValueError("users must be positive")
    if requests_per_user <= 0:
        raise ValueError("requests_per_user must be positive")
    if items_per_request <= 0:
        raise ValueError("items_per_request must be positive")
    if not candidates:
        raise ValueError("candidates must not be empty")

    rng = random.Random(seed)
    personas = prepare_personas(candidates)
    ranked_by_persona = {
        persona["persona_id"]: _rank_candidates_for_persona(persona, candidates, rng)
        for persona in personas
    }
    global_anchors = sorted(
        candidates,
        key=lambda candidate: (candidate.quality_score, candidate.num_hype_units),
        reverse=True,
    )[:DEFAULT_ANCHOR_ITEMS_PER_PERSONA]
    anchors_by_persona = {
        persona["persona_id"]: [
            candidate
            for candidate, _ in ranked_by_persona[persona["persona_id"]][:DEFAULT_ANCHOR_ITEMS_PER_PERSONA]
        ]
        for persona in personas
    }

    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    user_positive_items: dict[str, set[str]] = defaultdict(set)
    item_positive_users: dict[str, set[str]] = defaultdict(set)
    event_counts: Counter[str] = Counter()

    for user_index in range(users):
        persona = personas[user_index % len(personas)]
        persona_id = persona["persona_id"]
        user_id_hash = f"u_syn_{persona_id}_{user_index // len(personas) + 1:02d}"
        session_id = f"sess_syn_{seed}_{user_index:03d}"
        ranked = ranked_by_persona[persona_id]
        anchors = anchors_by_persona[persona_id]

        for request_index in range(requests_per_user):
            surface = "home" if request_index % 2 == 0 else "search"
            request_id = f"req_syn_{seed}_{user_index:03d}_{request_index:02d}"
            query_text = "" if surface == "home" else persona_query(persona)
            chosen = _choose_request_items(
                ranked=ranked,
                anchors=anchors,
                global_anchors=global_anchors,
                rng=rng,
                request_index=request_index,
                items_per_request=items_per_request,
            )

            items = []
            clicked_item_ids: set[str] = set()
            for rank_position, (candidate, final_score, sources) in enumerate(chosen, start=1):
                match_score = compute_persona_item_match(persona, candidate)
                items.append(
                    _candidate_item_payload(
                        candidate,
                        rank_position=rank_position,
                        final_score=final_score,
                        match_score=match_score,
                        candidate_sources=sources,
                    )
                )

                events.append(
                    {
                        "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "impression"),
                        "request_id": request_id,
                        "user_id_hash": user_id_hash,
                        "session_id": session_id,
                        "surface": surface,
                        "event_type": "impression",
                        "item_id": candidate.item_id,
                        "query_text": query_text,
                        "rank_position": rank_position,
                        "is_synthetic": True,
                        "client": {"component": "synthetic_seed", "device_type": "desktop"},
                        "metadata": {
                            "persona_id": persona_id,
                            "category_id": candidate.category_id,
                            "brand": candidate.brand,
                            "price_vnd": candidate.price_vnd,
                            "price_bucket": candidate.price_bucket,
                            "match_score": round(match_score, 6),
                        },
                    }
                )
                event_counts["impression"] += 1

                click_probability = simulate_click_probability(match_score, rank_position)
                clicked = rng.random() < min(0.75, click_probability * 0.55)
                if not clicked and rank_position <= 2 and request_index < 2 and match_score >= 0.55:
                    clicked = rng.random() < 0.25
                if clicked:
                    clicked_item_ids.add(candidate.item_id)
                    user_positive_items[user_id_hash].add(candidate.item_id)
                    item_positive_users[candidate.item_id].add(user_id_hash)
                    events.append(
                        {
                            "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "click"),
                            "request_id": request_id,
                            "user_id_hash": user_id_hash,
                            "session_id": session_id,
                            "surface": surface,
                            "event_type": "click",
                            "item_id": candidate.item_id,
                            "query_text": query_text,
                            "rank_position": rank_position,
                            "is_synthetic": True,
                            "client": {"component": "synthetic_seed", "device_type": "desktop"},
                            "metadata": {"persona_id": persona_id, "match_score": round(match_score, 6)},
                        }
                    )
                    event_counts["click"] += 1

                    cart_prob = cart_probability(match_score, clicked=True) * 0.35
                    if rng.random() < cart_prob:
                        events.append(
                            {
                                "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "add_to_cart"),
                                "request_id": request_id,
                                "user_id_hash": user_id_hash,
                                "session_id": session_id,
                                "surface": surface,
                                "event_type": "add_to_cart",
                                "item_id": candidate.item_id,
                                "query_text": query_text,
                                "rank_position": rank_position,
                                "is_synthetic": True,
                                "client": {"component": "synthetic_seed", "device_type": "desktop"},
                                "metadata": {"persona_id": persona_id, "match_score": round(match_score, 6)},
                            }
                        )
                        event_counts["add_to_cart"] += 1
                        if rng.random() < purchase_probability(cart_prob):
                            events.append(
                                {
                                    "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "purchase"),
                                    "request_id": request_id,
                                    "user_id_hash": user_id_hash,
                                    "session_id": session_id,
                                    "surface": surface,
                                    "event_type": "purchase",
                                    "item_id": candidate.item_id,
                                    "query_text": query_text,
                                    "rank_position": rank_position,
                                    "is_synthetic": True,
                                    "client": {"component": "synthetic_seed", "device_type": "desktop"},
                                    "metadata": {"persona_id": persona_id, "match_score": round(match_score, 6)},
                                }
                            )
                            event_counts["purchase"] += 1

            # Force limited positives on anchors so every user can feed profile/CF builders.
            if request_index == 0:
                for rank_position, (candidate, _, sources) in enumerate(chosen, start=1):
                    if "cross_persona_anchor" not in sources or candidate.item_id in clicked_item_ids:
                        continue
                    events.append(
                        {
                            "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "click", extra=2),
                            "request_id": request_id,
                            "user_id_hash": user_id_hash,
                            "session_id": session_id,
                            "surface": surface,
                            "event_type": "click",
                            "item_id": candidate.item_id,
                            "query_text": query_text,
                            "rank_position": rank_position,
                            "is_synthetic": True,
                            "client": {"component": "synthetic_seed_anchor", "device_type": "desktop"},
                            "metadata": {"persona_id": persona_id, "forced_cross_persona_anchor": True},
                        }
                    )
                    event_counts["click"] += 1
                    user_positive_items[user_id_hash].add(candidate.item_id)
                    item_positive_users[candidate.item_id].add(user_id_hash)
                    clicked_item_ids.add(candidate.item_id)
                    break

            if len(clicked_item_ids) < min(2, len(chosen)):
                for rank_position, (candidate, _, _) in enumerate(chosen[:3], start=1):
                    if candidate.item_id in clicked_item_ids:
                        continue
                    events.append(
                        {
                            "event_id": _event_id(seed, user_index, request_index, candidate.item_id, "click", extra=1),
                            "request_id": request_id,
                            "user_id_hash": user_id_hash,
                            "session_id": session_id,
                            "surface": surface,
                            "event_type": "click",
                            "item_id": candidate.item_id,
                            "query_text": query_text,
                            "rank_position": rank_position,
                            "is_synthetic": True,
                            "client": {"component": "synthetic_seed_anchor", "device_type": "desktop"},
                            "metadata": {"persona_id": persona_id, "forced_anchor_positive": True},
                        }
                    )
                    event_counts["click"] += 1
                    user_positive_items[user_id_hash].add(candidate.item_id)
                    item_positive_users[candidate.item_id].add(user_id_hash)
                    clicked_item_ids.add(candidate.item_id)
                    if len(clicked_item_ids) >= 2:
                        break

            requests.append(
                {
                    "request_id": request_id,
                    "user_id_hash": user_id_hash,
                    "session_id": session_id,
                    "surface": surface,
                    "persona_id": persona_id,
                    "query": {
                        "raw_query": query_text,
                        "english_query": query_text,
                        "query_type": "none" if surface == "home" else "normal",
                    },
                    "items": items,
                }
            )

    positive_counts = [len(items) for items in user_positive_items.values()]
    overlap_items = {
        item_id: len(users_for_item)
        for item_id, users_for_item in item_positive_users.items()
        if len(users_for_item) >= 2
    }
    summary = {
        "personas": len(personas),
        "users": users,
        "requests": len(requests),
        "recommendation_log_rows": sum(len(request["items"]) for request in requests),
        "clickstream_events": len(events),
        "event_counts": dict(sorted(event_counts.items())),
        "positive_items_per_user": {
            "min": min(positive_counts) if positive_counts else 0,
            "mean": round(mean(positive_counts), 2) if positive_counts else 0,
            "max": max(positive_counts) if positive_counts else 0,
        },
        "overlap_items_with_2plus_users": len(overlap_items),
        "top_overlap_items": sorted(overlap_items.items(), key=lambda item: item[1], reverse=True)[:10],
    }
    return {
        "personas": personas,
        "requests": requests,
        "events": events,
        "summary": summary,
        "samples": {
            "personas": [_persona_sample(persona) for persona in personas[:3]],
            "requests": requests[:2],
            "events": events[:5],
        },
    }


def _persona_sample(persona: dict[str, Any]) -> dict[str, Any]:
    sample = dict(persona)
    embedding = sample.pop("intent_embedding", None)
    if embedding:
        sample["intent_embedding_preview"] = embedding[:5]
    return sample


def _persona_doc(persona: dict[str, Any]) -> dict[str, Any]:
    doc = SyntheticPersonaDocument(**persona)
    payload = to_mongo_dict(doc)
    payload["_id"] = payload["persona_id"]
    return payload


def write_synthetic_behavior_plan(
    *,
    plan: dict[str, Any],
    synthetic_personas_collection: Any,
    recommendation_logs_collection: Any,
    clickstream_events_collection: Any,
) -> dict[str, Any]:
    persona_ops = []
    for persona in plan["personas"]:
        doc = _persona_doc(persona)
        persona_id = doc.pop("_id")
        persona_ops.append(
            UpdateOne(
                {"_id": persona_id},
                {"$set": doc, "$setOnInsert": {"_id": persona_id}},
                upsert=True,
            )
        )
    persona_result = synthetic_personas_collection.bulk_write(persona_ops, ordered=False) if persona_ops else None

    snapshot_inserted = 0
    snapshot_existing = 0
    for request in plan["requests"]:
        result = log_recommendation_snapshot(
            request_id=request["request_id"],
            user_id_hash=request["user_id_hash"],
            session_id=request["session_id"],
            surface=request["surface"],
            items=request["items"],
            query=request["query"],
            is_synthetic=True,
            recommendation_logs_collection=recommendation_logs_collection,
        )
        snapshot_inserted += int(result.get("inserted", 0))
        snapshot_existing += int(result.get("existing", 0))

    event_inserted = 0
    event_idempotent = 0
    for event in plan["events"]:
        result = log_clickstream_event(
            **event,
            clickstream_events_collection=clickstream_events_collection,
        )
        if result.get("inserted"):
            event_inserted += 1
        elif result.get("idempotent"):
            event_idempotent += 1

    return {
        "personas_upserted": int(getattr(persona_result, "upserted_count", 0)) if persona_result else 0,
        "personas_matched": int(getattr(persona_result, "matched_count", 0)) if persona_result else 0,
        "recommendation_logs_inserted": snapshot_inserted,
        "recommendation_logs_existing": snapshot_existing,
        "clickstream_events_inserted": event_inserted,
        "clickstream_events_idempotent": event_idempotent,
    }
