from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes_evaluation import sanitize_evaluation_run_document


class FakeObjectId:
    def __str__(self) -> str:
        return "fake_object_id"


class FakeCursor(list):
    def sort(self, field_name: str, direction: int):
        reverse = direction < 0
        return FakeCursor(sorted(self, key=lambda doc: str(doc.get(field_name) or ""), reverse=reverse))

    def limit(self, n: int):
        return FakeCursor(self[:n])


class ReadOnlyFakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def find(self, *_args, **_kwargs):
        return FakeCursor(self.docs)

    def find_one(self, filter_doc):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                return dict(doc)
        return None

    def insert_one(self, *_args, **_kwargs):
        raise AssertionError("evaluation dashboard API must be read-only")

    def update_one(self, *_args, **_kwargs):
        raise AssertionError("evaluation dashboard API must be read-only")

    def delete_many(self, *_args, **_kwargs):
        raise AssertionError("evaluation dashboard API must be read-only")


def _doc(run_id: str, created_at: str) -> dict:
    return {
        "_id": FakeObjectId(),
        "run_id": run_id,
        "run_type": "personalization_eval",
        "algorithm_version": "algo_v1",
        "ranking_version": "rank_v1",
        "data_label": "synthetic/demo evaluation",
        "synthetic_data": True,
        "evaluation_data_mode": "synthetic_demo",
        "metrics": {
            "baseline_count": 2,
            "comparison_count": 1,
            "cohort_diagnostics": {"sparse_user_count": 3},
        },
        "baseline_summaries": [
            {
                "baseline": "profile_plus_cf",
                "hit_rate_at_10": 0.12,
                "recall_at_20": 0.08,
                "map_at_20": 0.04,
                "coverage": 0.2,
                "cf_supported_recommendation_count": 10,
            }
        ],
        "comparisons": [{"comparison": "profile_plus_cf_vs_profile_only", "map_at_20_delta": 0.02}],
        "live_state_counts": {"items": 3000, "user_profiles": 43},
        "caveat": "Synthetic/demo behavior data, not production traffic.",
        "evaluated_user_count": 42,
        "artifacts": {"written": False, "path": None, "files": {"internal": ".runtime/secret-not-secret"}},
        "created_at": created_at,
        "per_user_metrics": [{"user_id_hash": "u_raw_should_not_leak"}],
        "raw_events": [{"event_id": "evt_raw_should_not_leak"}],
    }


def _client(monkeypatch, docs: list[dict]) -> TestClient:
    import src.api.routes_evaluation as routes_evaluation

    monkeypatch.setattr(routes_evaluation, "get_evaluation_runs_collection", lambda: ReadOnlyFakeCollection(docs))
    return TestClient(create_app())


def test_latest_evaluation_run_empty_state(monkeypatch) -> None:
    client = _client(monkeypatch, [])

    response = client.get("/api/evaluation/runs/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["latest"] is None
    assert "No persisted evaluation runs yet" in payload["message"]


def test_latest_evaluation_run_returns_sanitized_newest_doc(monkeypatch) -> None:
    docs = [_doc("old_run", "2026-01-01T00:00:00+00:00"), _doc("new_run", "2026-05-25T00:00:00+00:00")]
    client = _client(monkeypatch, docs)

    response = client.get("/api/evaluation/runs/latest")

    assert response.status_code == 200
    latest = response.json()["latest"]
    assert latest["id"] == "fake_object_id"
    assert latest["run_id"] == "new_run"
    assert latest["algorithm_version"] == "algo_v1"
    assert latest["ranking_version"] == "rank_v1"
    assert latest["evaluation_data_mode"] == "synthetic_demo"
    assert "Synthetic/demo behavior data" in latest["caveat"]
    assert "per_user_metrics" not in latest
    assert "raw_events" not in latest
    assert latest["artifacts"] == {"written": False, "path": None}


def test_list_evaluation_runs_caps_limit_and_orders_newest_first(monkeypatch) -> None:
    docs = [_doc(f"run_{index:02d}", f"2026-05-{index + 1:02d}T00:00:00+00:00") for index in range(60)]
    client = _client(monkeypatch, docs)

    response = client.get("/api/evaluation/runs?limit=999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 50
    assert len(payload["runs"]) == 50
    assert payload["runs"][0]["run_id"] == "run_59"


def test_evaluation_run_detail_found_and_not_found(monkeypatch) -> None:
    client = _client(monkeypatch, [_doc("target_run", "2026-05-25T00:00:00+00:00")])

    found = client.get("/api/evaluation/runs/target_run")
    missing = client.get("/api/evaluation/runs/missing_run")

    assert found.status_code == 200
    assert found.json()["run"]["run_id"] == "target_run"
    assert missing.status_code == 404
    assert missing.json()["detail"]["error"] == "not_found"


def test_sanitize_evaluation_run_document_drops_heavy_raw_payloads() -> None:
    sanitized = sanitize_evaluation_run_document(_doc("sanitize_run", "2026-05-25T00:00:00+00:00"))

    assert sanitized is not None
    assert sanitized["run_id"] == "sanitize_run"
    assert sanitized["metrics"]["cohort_diagnostics"]["sparse_user_count"] == 3
    assert "per_user_metrics" not in sanitized
    assert "raw_events" not in sanitized
    assert "u_raw_should_not_leak" not in str(sanitized)
    assert "evt_raw_should_not_leak" not in str(sanitized)
