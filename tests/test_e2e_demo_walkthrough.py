"""
Deterministic E2E walkthrough for a user shaped like phuc_demo.
See RECOMMENDATION_ENHANCEMENT_PLAN_AFTER_AUDIT.md §14.3.

Scenario:
  1. User searches for sensitive-skin soap.             (query-first ranking; see test_recommendation_scoring.py)
  2. User opens the soap item and adds it to cart.
  3. User browses several smartphone items briefly (click + short dwell < 5 s).
  4. User returns to the home feed.
  5. Explanations and score breakdown are inspected.

Expected outcomes verified here:
  - Beauty/cart signal is seed_eligible; short smartphone clicks are NOT seed_eligible.
  - Cart deliberate contribution materially exceeds exploratory phone browsing.
  - Home feed: beauty card displays only a beauty-sourced profile reason.
  - Home feed: AMOLED product fact does not appear as a profile badge or reason.
  - Home feed: CF badge is absent when no multi-user edge contributed.
  - Impression-only items produce exposure-tier signals that are never seed_eligible.
  - Debug freshness endpoint reports state=current after all events are processed
    and stored versions match the configured runtime versions.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.intent_hygiene import sanitize_interest_labels
from src.behavior.signal_builder import build_signal_artifacts
from src.config import get_settings
from src.recommendation.explanations import build_result_card
from src.recommendation.scoring import score_candidate_batch


# ---------------------------------------------------------------------------
# Shared walkthrough fixture
# ---------------------------------------------------------------------------

_TS = "2026-05-25T10:00:00Z"
_SESSION = "sess_walkthrough"
_USER = "u_walkthrough"
_REQ_SEARCH = "req_search_soap"

# Events produced by steps 2-3 of the walkthrough scenario.
WALKTHROUGH_EVENTS: list[dict] = [
    # Step 2: open soap item (click + medium dwell) then add to cart — conversion tier.
    {
        "event_id": "evt_w01",
        "user_id_hash": _USER,
        "item_id": "B_SOAP_001",
        "event_type": "click",
        "surface": "search",
        "session_id": _SESSION,
        "request_id": _REQ_SEARCH,
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w02",
        "user_id_hash": _USER,
        "item_id": "B_SOAP_001",
        "event_type": "view_detail",
        "surface": "detail",
        "session_id": _SESSION,
        "request_id": _REQ_SEARCH,
        "dwell_time_ms": 8000,  # engaged tier: >= 5 000 ms, < 20 000 ms
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w03",
        "user_id_hash": _USER,
        "item_id": "B_SOAP_001",
        "event_type": "add_to_cart",
        "surface": "detail",
        "session_id": _SESSION,
        "request_id": _REQ_SEARCH,
        "timestamp": _TS,
    },
    # Step 3: brief smartphone browsing — exploratory only (< 5 000 ms dwell).
    {
        "event_id": "evt_w04",
        "user_id_hash": _USER,
        "item_id": "P_PHONE_001",
        "event_type": "click",
        "surface": "search",
        "session_id": _SESSION,
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w05",
        "user_id_hash": _USER,
        "item_id": "P_PHONE_001",
        "event_type": "view_detail",
        "surface": "detail",
        "session_id": _SESSION,
        "dwell_time_ms": 2000,  # exploratory tier: < 5 000 ms
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w06",
        "user_id_hash": _USER,
        "item_id": "P_PHONE_002",
        "event_type": "click",
        "surface": "search",
        "session_id": _SESSION,
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w07",
        "user_id_hash": _USER,
        "item_id": "P_PHONE_002",
        "event_type": "view_detail",
        "surface": "detail",
        "session_id": _SESSION,
        "dwell_time_ms": 1500,  # exploratory tier: < 5 000 ms
        "timestamp": _TS,
    },
    {
        "event_id": "evt_w08",
        "user_id_hash": _USER,
        "item_id": "P_PHONE_003",
        "event_type": "click",
        "surface": "search",
        "session_id": _SESSION,
        "timestamp": _TS,
    },
]


# ---------------------------------------------------------------------------
# 1. Seed eligibility
# ---------------------------------------------------------------------------


def test_walkthrough_cart_item_is_seed_eligible_and_short_phone_clicks_are_not() -> None:
    """Cart + medium-dwell soap is seed_eligible; exploratory phone clicks are not."""
    artifacts = build_signal_artifacts(events=WALKTHROUGH_EVENTS, updated_at=_TS)
    by_item = {doc["item_id"]: doc for doc in artifacts.signal_docs}

    soap = by_item["B_SOAP_001"]
    assert soap["seed_eligible"] is True, "Cart item must be seed_eligible"
    assert soap["intent_tier"] == "conversion"
    assert soap["contributions"]["conversion"] > 0

    for phone_id in ("P_PHONE_001", "P_PHONE_002", "P_PHONE_003"):
        phone = by_item[phone_id]
        assert phone["seed_eligible"] is False, (
            f"{phone_id} has only exploratory events and must not be seed_eligible"
        )
        assert phone["intent_tier"] in ("exploratory", "engaged")


# ---------------------------------------------------------------------------
# 2. Deliberate score ordering
# ---------------------------------------------------------------------------


def test_walkthrough_cart_deliberate_score_materially_exceeds_exploratory_phone_score() -> None:
    """Add-to-cart deliberate contribution must dominate isolated click/short-dwell browsing."""
    artifacts = build_signal_artifacts(events=WALKTHROUGH_EVENTS, updated_at=_TS)
    by_item = {doc["item_id"]: doc for doc in artifacts.signal_docs}

    def deliberate(doc: dict) -> float:
        c = doc.get("contributions", {})
        return float(c.get("engaged", 0.0)) + float(c.get("conversion", 0.0))

    soap_deliberate = deliberate(by_item["B_SOAP_001"])
    max_phone_deliberate = max(
        deliberate(by_item[pid]) for pid in ("P_PHONE_001", "P_PHONE_002", "P_PHONE_003")
    )

    assert soap_deliberate > max_phone_deliberate
    assert soap_deliberate >= get_settings().signal_seed_eligible_min_deliberate_score


# ---------------------------------------------------------------------------
# 3. Impression-only items stay in exposure tier
# ---------------------------------------------------------------------------


def test_walkthrough_impression_only_item_is_exposure_tier_not_seed_eligible() -> None:
    """A page impression alone must not qualify an item as a personalization seed."""
    events = [
        {
            "event_id": "evt_imp_01",
            "user_id_hash": _USER,
            "item_id": "IMPRESSION_ONLY",
            "event_type": "impression",
            "surface": "home",
            "session_id": _SESSION,
            "timestamp": _TS,
        }
    ]
    artifacts = build_signal_artifacts(events=events, updated_at=_TS)
    by_item = {doc["item_id"]: doc for doc in artifacts.signal_docs}

    doc = by_item["IMPRESSION_ONLY"]
    assert doc["seed_eligible"] is False
    assert doc["intent_tier"] == "exposure"
    assert doc["positive_score"] == 0.0


# ---------------------------------------------------------------------------
# 4. Profile label hygiene
# ---------------------------------------------------------------------------


def test_walkthrough_amoled_product_fact_is_rejected_as_interest_label() -> None:
    """Spec-marker-heavy product facts, UUIDs, and generic strings must be rejected."""
    settings = get_settings()
    amoled_fact = (
        "The smartphone has a 6.4-inch Super AMOLED capacitive touchscreen with 16M colors."
    )
    uuid_like = "550e8400-e29b-41d4-a716-446655440000"
    generic = "interest"
    valid_label = "sensitive skin person looking for natural soap"

    accepted, dropped = sanitize_interest_labels(
        [amoled_fact, uuid_like, generic, valid_label],
        max_length=settings.profile_label_max_length,
    )

    assert dropped >= 3, "AMOLED fact, UUID, and generic label must all be rejected"
    assert amoled_fact not in accepted
    assert uuid_like not in accepted
    assert generic not in accepted
    assert valid_label in accepted


# ---------------------------------------------------------------------------
# 5. Beauty card reason — no cross-category contamination
# ---------------------------------------------------------------------------


def test_walkthrough_beauty_card_reason_is_beauty_interest_not_smartphone_fact() -> None:
    """Profile badge on a beauty card must cite the beauty interest, not an AMOLED fact."""
    card = build_result_card(
        {
            "item_id": "B_SOAP_001",
            "profile_interest_label": "sensitive skin person looking for natural soap",
            "matched_intent": "AMOLED smartphone display",         # contamination attempt
            "matched_fact": "Super AMOLED capacitive touchscreen",  # contamination attempt
            "matched_channels": ["profile"],
            "candidate_sources": ["profile"],
            "contributions": {"profile": 0.45, "quality": 0.10},
            "final_score": 0.55,
        },
        request_id="req_home_walk",
        rank_position=1,
        surface="home",
        algorithm_version="rec_v2_negative_suppression_seed_guard",
        ranking_version="rank_v1_default_weights",
    )

    joined = " ".join(card["explanations"]).lower()
    assert "amoled" not in joined, "AMOLED fact must not appear in beauty card explanation"
    assert "touchscreen" not in joined, "touchscreen spec must not appear in beauty card explanation"
    assert "natural soap" in joined or "sensitive skin" in joined
    assert "Profile" in card["reason_badges"]
    assert card["attribution"]["primary_reason_channel"] == "profile"


# ---------------------------------------------------------------------------
# 6. No CF badge without multi-user edge
# ---------------------------------------------------------------------------


def test_walkthrough_no_cf_badge_without_multi_user_edge() -> None:
    """A candidate whose CF contribution is zero must not receive a CF reason badge."""
    card = build_result_card(
        {
            "item_id": "P_PHONE_CANDIDATE",
            "matched_channels": ["cf"],
            "candidate_sources": ["cf"],
            "contributions": {"cf": 0.0},  # no supported multi-user edge contributed
            "final_score": 0.15,
        },
        request_id="req_home_walk",
        rank_position=5,
        surface="home",
        algorithm_version="rec_v2_negative_suppression_seed_guard",
        ranking_version="rank_v1_default_weights",
    )

    assert "Collaborative Filtering" not in card["reason_badges"]
    assert card["attribution"]["primary_reason_channel"] != "cf"


# ---------------------------------------------------------------------------
# 7. Query-first: specific query keeps query-relevant item above profile-heavy item
# ---------------------------------------------------------------------------


def test_walkthrough_specific_soap_query_ranks_query_relevant_item_first() -> None:
    """Step 1: search result must be dominated by query relevance, not profile bias."""
    from src.recommendation.scoring import get_search_weights

    candidates = [
        {
            "item_id": "B_SOAP_QUERY_MATCH",
            "query_hybrid_score_raw": 0.92,
            "profile_score_raw": 0.10,
            "metadata_score_raw": 0.40,
        },
        {
            "item_id": "B_SOAP_PROFILE_HEAVY",
            "query_hybrid_score_raw": 0.25,
            "profile_score_raw": 0.90,
            "metadata_score_raw": 0.40,
        },
    ]
    ranked = score_candidate_batch(candidates, get_search_weights("specific"))

    assert ranked[0]["item_id"] == "B_SOAP_QUERY_MATCH", (
        "Query-relevant item must rank above profile-heavy item on a specific query"
    )


# ---------------------------------------------------------------------------
# 8. Debug freshness: state=current after all events are processed and versions align
# ---------------------------------------------------------------------------


def test_walkthrough_debug_freshness_state_is_current_after_processing(monkeypatch) -> None:
    """Step 5: debug view must report state=current once events are fully processed."""
    import src.api.routes_debug as routes_debug
    from fastapi.testclient import TestClient

    from src.api.app import create_app

    settings = get_settings()
    signal_version = settings.signal_model_version
    profile_version = settings.profile_model_version
    cf_version = settings.cf_model_version
    cf_policy = settings.cf_runtime_input_policy

    # All events processed; signal/profile built after events; CF built after signals.
    processed_signal = {
        "user_id_hash": _USER,
        "item_id": "B_SOAP_001",
        "implicit_score": 4.5,
        "derivation": {
            "model_version": signal_version,
            "built_at": "2026-05-25T11:00:00Z",
            "source_event_max_timestamp": _TS,
        },
        "updated_at": "2026-05-25T11:00:00Z",
    }
    processed_profile = {
        "user_id_hash": _USER,
        "profile_status": "warm",
        "derivation": {
            "model_version": profile_version,
            "source_signal_model_version": signal_version,
            "source_signal_built_at": "2026-05-25T11:00:00Z",
            "built_at": "2026-05-25T11:00:00Z",
        },
        "updated_at": "2026-05-25T11:00:00Z",
    }
    processed_event = {
        "event_id": "evt_w01",
        "user_id_hash": _USER,
        "item_id": "B_SOAP_001",
        "event_type": "add_to_cart",
        "processed": True,
        "timestamp": _TS,
    }
    cf_edge = {
        "item_id": "B_SOAP_001",
        "neighbor_item_id": "B_SOAP_002",
        "derivation": {
            "model_version": cf_version,
            "source_signal_model_version": signal_version,
            "source_signal_built_at": "2026-05-25T11:00:00Z",
            "built_at": "2026-05-25T11:30:00Z",
            "input_policy": cf_policy,
        },
        "updated_at": "2026-05-25T11:30:00Z",
    }

    class _FakeCollection:
        """Minimal cursor-compatible fake for monkeypatching MongoDB collection getters."""

        def __init__(self, docs: list) -> None:
            self._docs = docs

        def find_one(self, _filter=None, _projection=None):
            return dict(self._docs[0]) if self._docs else None

        def find(self, _filter=None, _projection=None):
            return self  # acts as its own cursor

        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n: int):
            return self._docs[:n]

        def count_documents(self, _filter=None) -> int:
            return 0  # all events are processed → pending_event_count = 0

    monkeypatch.setattr(routes_debug, "get_users_collection",
                        lambda: _FakeCollection([{"user_id_hash": _USER}]))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection",
                        lambda: _FakeCollection([processed_profile]))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection",
                        lambda: _FakeCollection([processed_signal]))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection",
                        lambda: _FakeCollection([]))
    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection",
                        lambda: _FakeCollection([processed_event]))
    monkeypatch.setattr(routes_debug, "get_item_item_cf_edges_collection",
                        lambda: _FakeCollection([cf_edge]))

    admin_token = "test-admin-token"
    monkeypatch.setenv("ADMIN_TOKEN", admin_token)

    client = TestClient(create_app())
    resp = client.get(f"/api/debug/user/{_USER}", headers={"X-Admin-Token": admin_token})
    assert resp.status_code == 200

    freshness = resp.json()["freshness"]
    assert freshness["state"] == "current", (
        f"Expected freshness.state=current but got {freshness['state']!r}; "
        f"stale_components={freshness.get('stale_components')}, "
        f"stale_version_components={freshness.get('model_versions', {}).get('stale_version_components')}"
    )
    assert freshness["pending_event_count"] == 0
    assert freshness["components"]["signals"]["state"] == "current"
    assert freshness["components"]["profile"]["state"] == "current"
    assert freshness["components"]["cf"]["state"] == "current"
    assert freshness["components"]["cf"]["input_policy"] == cf_policy
