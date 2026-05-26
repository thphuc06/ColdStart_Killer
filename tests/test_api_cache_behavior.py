from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.cache.service import reset_cache_backend_for_tests


ADMIN_TOKEN = "test-admin-token"


class FakeCursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        return FakeCursor(self[:n])


class FakeEvaluationRunsCollection:
    def __init__(self) -> None:
        self.find_calls = 0

    def find(self, *_args, **_kwargs):
        self.find_calls += 1
        return FakeCursor(
            [
                {
                    "_id": "object_id_1",
                    "run_id": "eval_1",
                    "algorithm_version": "rec_v1",
                    "ranking_version": "rank_v1",
                    "created_at": "2026-05-26T00:00:00+00:00",
                    "per_user_metrics": [{"raw": "dropped"}],
                }
            ]
        )

    def find_one(self, *_args, **_kwargs):
        return None


class RecordingCache:
    backend_name = "recording"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.store = {}
        self.keys: list[str] = []

    def get(self, key):
        self.keys.append(key)
        if self.fail:
            raise RuntimeError("cache get failed")
        return self.store.get(key)

    def set(self, key, value, ttl_seconds=None):
        self.keys.append(key)
        if self.fail:
            raise RuntimeError("cache set failed")
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def clear_namespace(self, namespace):
        for key in list(self.store):
            if f":{namespace}:" in key:
                self.store.pop(key, None)

    def status(self):
        return {"backend": self.backend_name}


def test_evaluation_latest_uses_cache_on_second_call(monkeypatch) -> None:
    import src.api.routes_evaluation as routes_evaluation

    reset_cache_backend_for_tests()
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    monkeypatch.setenv("CACHE_KEY_VERSION", "test_cache")
    collection = FakeEvaluationRunsCollection()
    monkeypatch.setattr(routes_evaluation, "get_evaluation_runs_collection", lambda: collection)

    client = TestClient(create_app())
    first = client.get("/api/evaluation/runs/latest")
    second = client.get("/api/evaluation/runs/latest")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert collection.find_calls == 1
    assert "per_user_metrics" not in first.text


def test_cache_failure_falls_back_to_compute(monkeypatch) -> None:
    import src.api.routes_evaluation as routes_evaluation

    collection = FakeEvaluationRunsCollection()
    monkeypatch.setattr(routes_evaluation, "get_evaluation_runs_collection", lambda: collection)
    monkeypatch.setattr(routes_evaluation, "get_cache_backend", lambda: RecordingCache(fail=True))

    client = TestClient(create_app())
    response = client.get("/api/evaluation/runs/latest")

    assert response.status_code == 200
    assert response.json()["latest"]["run_id"] == "eval_1"
    assert collection.find_calls == 1


def test_jobs_registry_cache_key_does_not_include_admin_token(monkeypatch) -> None:
    import src.api.routes_jobs as routes_jobs

    cache = RecordingCache()
    calls = {"count": 0}

    def fake_registry():
        calls["count"] += 1
        return [{"job_type": "fusion_comparison_dry_run", "label": "Fusion"}]

    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(routes_jobs, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(routes_jobs, "get_job_registry_payload", fake_registry)

    client = TestClient(create_app())
    headers = {"X-Admin-Token": ADMIN_TOKEN}
    assert client.get("/api/jobs/registry", headers=headers).status_code == 200
    assert client.get("/api/jobs/registry", headers=headers).status_code == 200

    assert calls["count"] == 1
    assert not any(ADMIN_TOKEN in key for key in cache.keys)


def test_jobs_run_post_is_not_cached_when_trigger_disabled(monkeypatch) -> None:
    import src.api.routes_jobs as routes_jobs

    cache = RecordingCache()
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "false")
    monkeypatch.setattr(routes_jobs, "get_cache_backend", lambda: cache)

    client = TestClient(create_app())
    response = client.post(
        "/api/jobs/run",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"job_type": "fusion_comparison_dry_run", "dry_run": True, "params": {}},
    )

    assert response.status_code == 403
    assert cache.keys == []
