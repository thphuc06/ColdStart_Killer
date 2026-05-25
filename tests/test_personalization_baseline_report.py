from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import report_personalization_baseline as report_script


class FakeProfilesCollection:
    def __init__(self, doc: dict) -> None:
        self.doc = dict(doc)

    def find_one(self, _filter_doc: dict, _projection: dict | None = None):
        return dict(self.doc)


def test_build_personalization_baseline_report_counts_invalid_labels_and_writes_artifacts(tmp_path, monkeypatch) -> None:
    uuid_like_label = "550e8400-e29b-41d4-a716-446655440000"
    monkeypatch.setattr(
        report_script,
        "get_user_profiles_collection",
        lambda: FakeProfilesCollection(
            {
                "user_id_hash": "u_demo",
                "profile_status": "warm",
                "interest_vectors": [
                    {"label": "sensitive skin", "top_intents": ["sensitive skin"], "categories": ["all_beauty"]},
                    {"label": uuid_like_label, "top_intents": [uuid_like_label], "categories": ["all_beauty"]},
                    {"label": "interest", "top_intents": [], "categories": []},
                ],
                "intent_affinity": [{"intent": "sensitive skin", "score": 1.0}],
                "negative_preferences": {"item_ids": [], "brands": [], "categories": [], "intents": []},
            }
        ),
    )
    monkeypatch.setattr(
        report_script,
        "get_debug_user",
        lambda user_id: {
            "user_id_hash": user_id,
            "freshness": {
                "state": "current",
                "pending_event_count": 0,
                "model_versions": {
                    "stored": {"signal_model_version": "signal_v3_intent_hierarchy"},
                    "configured": {"signal_model_version": "signal_v3_intent_hierarchy"},
                },
            },
        },
    )
    monkeypatch.setattr(
        report_script,
        "load_user_signals",
        lambda *args, **kwargs: [
            {
                "item_id": "B001",
                "seed_eligible": True,
                "intent_tier": "engaged",
                "contributions": {"exploratory": 0.35, "engaged": 0.75, "conversion": 0.0},
                "reason_scores": [{"intent": "sensitive skin", "score": 0.8}],
            }
        ],
    )
    monkeypatch.setattr(
        report_script,
        "get_homepage_feed",
        lambda *args, **kwargs: {
            "request_id": "req_home_test",
            "snapshot": {"ok": True, "attempted": 2, "inserted": 2},
            "items": [
                {
                    "item_id": "B001",
                    "reason_badges": ["Profile"],
                    "explanations": ["Boosted because it matches your sensitive skin interest."],
                    "debug": {"profile_interest_label": "sensitive skin"},
                },
                {
                    "item_id": "B002",
                    "reason_badges": ["Profile"],
                    "explanations": [
                        "Boosted because it matches your 550e8400-e29b-41d4-a716-446655440000 interest.",
                        "Matched product fact: The smartphone has a 6.4-inch Super AMOLED capacitive touchscreen with 16M colors.",
                    ],
                    "debug": {"profile_interest_label": uuid_like_label},
                },
            ],
        },
    )

    report = report_script.build_personalization_baseline_report(
        user_id="u_demo",
        session_id="sess_demo",
        top_k=2,
        signals_limit=3,
    )

    assert report["counters"]["uuid_label_count"] == 1
    assert report["counters"]["generic_label_count"] == 1
    assert report["counters"]["profile_explanation_audit_failures"] == 2

    out_dir = tmp_path / "baseline"
    report_script.write_report_artifacts(report, out_dir)

    json_payload = json.loads((out_dir / "personalization_baseline.json").read_text(encoding="utf-8"))
    assert json_payload["user_id"] == "u_demo"
    assert (out_dir / "personalization_baseline.md").exists()