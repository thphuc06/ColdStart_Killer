from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app


ADMIN_TOKEN = "test-admin-token"


class FakeCursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        return FakeCursor(self[:n])


class FakeJobRunsCollection:
    def __init__(self, docs=None) -> None:
        self.docs = list(docs or [])
        self.inserted = []
        self.updated = []

    def find(self, *_args, **_kwargs):
        return FakeCursor(self.docs)

    def find_one(self, query):
        return next((doc for doc in self.docs if doc.get("job_run_id") == query.get("job_run_id")), None)

    def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)

    def update_one(self, query, update):
        self.updated.append((query, update))
        for doc in self.docs:
            if doc.get("job_run_id") == query.get("job_run_id"):
                doc.update(update.get("$set", {}))

    def delete_many(self, *_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("delete_many must not be called by jobs API")


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    return TestClient(create_app())


def _headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


def test_get_registry_returns_jobs_and_trigger_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "false")
    client = _client(monkeypatch)
    response = client.get("/api/jobs/registry", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["trigger_api_enabled"] is False
    assert any(job["job_type"] == "fusion_comparison_dry_run" for job in payload["jobs"])


def test_get_runs_empty_state(monkeypatch) -> None:
    import src.api.routes_jobs as routes_jobs

    monkeypatch.setattr(routes_jobs, "get_job_runs_collection", lambda: FakeJobRunsCollection())
    client = _client(monkeypatch)
    response = client.get("/api/jobs/runs", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["runs"] == []


def test_get_run_detail_not_found(monkeypatch) -> None:
    import src.api.routes_jobs as routes_jobs

    monkeypatch.setattr(routes_jobs, "get_job_runs_collection", lambda: FakeJobRunsCollection())
    client = _client(monkeypatch)
    response = client.get("/api/jobs/runs/jobrun_missing", headers=_headers())
    assert response.status_code == 404


def test_post_run_rejected_when_trigger_api_disabled(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/api/jobs/run",
        headers=_headers(),
        json={"job_type": "fusion_comparison_dry_run", "dry_run": True, "params": {}},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "job_trigger_api_disabled"


def test_post_dry_run_succeeds_when_trigger_api_enabled(monkeypatch) -> None:
    import src.api.routes_jobs as routes_jobs

    collection = FakeJobRunsCollection()
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "true")
    monkeypatch.setattr(routes_jobs, "get_job_runs_collection", lambda: collection)
    client = _client(monkeypatch)
    response = client.post(
        "/api/jobs/run",
        headers=_headers(),
        json={"job_type": "fusion_comparison_dry_run", "dry_run": True, "params": {"query": "coffee maker"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["run"]["status"] == "dry_run_completed"
    assert len(collection.inserted) == 1
    assert collection.updated[-1][1]["$set"]["status"] == "dry_run_completed"


def test_post_write_job_rejected_from_api(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "true")
    client = _client(monkeypatch)
    response = client.post(
        "/api/jobs/run",
        headers=_headers(),
        json={"job_type": "run_evaluation_write", "dry_run": False, "write": True, "confirm": "EVAL_RUN_WRITE"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "write_jobs_disabled_from_api"
