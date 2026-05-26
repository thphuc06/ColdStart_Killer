from __future__ import annotations

from src.cache.keys import make_cache_key


def test_cache_key_is_stable_for_same_input() -> None:
    left = make_cache_key("evaluation", {"limit": 10, "kind": "latest"}, version="v1")
    right = make_cache_key("evaluation", {"kind": "latest", "limit": 10}, version="v1")
    assert left == right


def test_cache_key_changes_with_version() -> None:
    assert make_cache_key("jobs", "registry", version="v1") != make_cache_key("jobs", "registry", version="v2")


def test_long_parts_are_hashed() -> None:
    raw = "x" * 200
    key = make_cache_key("search", {"query": raw}, version="v1")
    assert raw not in key
    assert "h=" in key


def test_secrets_are_not_exposed_in_key() -> None:
    key = make_cache_key(
        "jobs",
        {"ADMIN_TOKEN": "super-secret-token", "limit": 20, "MONGODB_URI": "mongodb+srv://hidden"},
        version="v1",
    )
    assert "super-secret-token" not in key
    assert "mongodb+srv" not in key
    assert "[redacted]" not in key


def test_simple_parts_are_readable() -> None:
    assert make_cache_key("jobs", {"limit": 20}, version="v1") == "v1:jobs:limit=20"
