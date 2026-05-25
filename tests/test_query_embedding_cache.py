from __future__ import annotations

from dataclasses import replace

from src.config import get_settings
from src.recommendation.query_cache import build_query_cache_key, process_query_with_cache


def _settings(**overrides):
    base = replace(
        get_settings(),
        enable_query_embedding_cache=True,
        query_cache_write_enabled=False,
        query_cache_version="query_cache_v1",
        query_cache_ttl_days=0,
        embedding_model="BAAI/bge-m3",
        vector_index_name="vector_index",
        text_index_name="text_index",
        algorithm_version="algo_v1",
        ranking_version="rank_v1",
    )
    return replace(base, **overrides)


def _fixture(raw_query: str = "iphone case") -> dict:
    return {
        "original_query": raw_query,
        "language_detected": "en",
        "english_query": raw_query,
        "hype_search_query_en": f"user looking for {raw_query} for everyday use",
        "bm25_search_query_en": raw_query,
        "hard_filters": {"in_stock": True},
        "query_embedding": [0.0] * 1024,
    }


def _cache_doc(raw_query: str = "iphone case", settings=None, fixture: dict | None = None) -> dict:
    active_settings = settings or _settings()
    processed_query = fixture or _fixture(raw_query)
    query_hash = build_query_cache_key(raw_query, settings=active_settings)
    return {
        "query_hash": query_hash,
        "raw_query": raw_query,
        "normalized_query": raw_query.lower(),
        "english_query": processed_query["english_query"],
        "embedding": list(processed_query["query_embedding"]),
        "processed_query": dict(processed_query),
        "embedding_model": active_settings.embedding_model,
        "vector_index_name": active_settings.vector_index_name,
        "text_index_name": active_settings.text_index_name,
        "query_cache_version": active_settings.query_cache_version,
        "algorithm_version": active_settings.algorithm_version,
        "ranking_version": active_settings.ranking_version,
        "created_at": "2026-05-25T00:00:00+00:00",
        "last_used_at": "2026-05-25T00:00:00+00:00",
        "usage_count": 1,
    }


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None, *, read_error: bool = False, write_error: bool = False):
        self.docs = {doc["query_hash"]: dict(doc) for doc in (docs or [])}
        self.find_one_calls: list[dict] = []
        self.update_one_calls: list[tuple[dict, dict, bool]] = []
        self.read_error = read_error
        self.write_error = write_error

    def find_one(self, filter_doc):
        self.find_one_calls.append(dict(filter_doc))
        if self.read_error:
            raise RuntimeError("simulated read error")
        doc = self.docs.get(filter_doc.get("query_hash"))
        return dict(doc) if doc is not None else None

    def update_one(self, filter_doc, update_doc, upsert=False):
        self.update_one_calls.append((dict(filter_doc), dict(update_doc), bool(upsert)))
        if self.write_error:
            raise RuntimeError("simulated write error")
        query_hash = filter_doc["query_hash"]
        existing = self.docs.get(query_hash)
        if existing is None:
            if not upsert:
                return object()
            existing = {}
            existing.update(update_doc.get("$setOnInsert", {}))
        existing.update(update_doc.get("$set", {}))
        for key, delta in update_doc.get("$inc", {}).items():
            existing[key] = existing.get(key, 0) + delta
        self.docs[query_hash] = existing
        return object()


class ExplodingCollection:
    def find_one(self, *_args, **_kwargs):
        raise AssertionError("cache collection should not be read")

    def update_one(self, *_args, **_kwargs):
        raise AssertionError("cache collection should not be written")


def test_build_query_cache_key_is_stable_and_versioned() -> None:
    settings = _settings()
    first = build_query_cache_key("iPhone case under 300k", settings=settings)
    second = build_query_cache_key(" iPhone   case under 300k ", settings=settings)
    changed_query = build_query_cache_key("wireless charger under 300k", settings=settings)
    changed_version = build_query_cache_key(
        "iPhone case under 300k",
        settings=_settings(query_cache_version="query_cache_v2"),
    )
    changed_model = build_query_cache_key(
        "iPhone case under 300k",
        settings=_settings(embedding_model="other-model"),
    )

    assert first == second
    assert first != changed_query
    assert first != changed_version
    assert first != changed_model


def test_cache_disabled_does_not_read_collection_and_returns_process_query_result() -> None:
    calls = []

    def fake_process(raw_query: str) -> dict:
        calls.append(raw_query)
        return _fixture(raw_query)

    result = process_query_with_cache(
        "iphone case",
        process_query_fn=fake_process,
        settings=_settings(enable_query_embedding_cache=False),
        collection=ExplodingCollection(),
    )

    assert calls == ["iphone case"]
    assert result["original_query"] == "iphone case"


def test_cache_miss_falls_back_without_write_when_write_disabled() -> None:
    collection = FakeCollection()
    calls = []

    result = process_query_with_cache(
        "iphone case",
        process_query_fn=lambda raw_query: calls.append(raw_query) or _fixture(raw_query),
        settings=_settings(query_cache_write_enabled=False),
        collection=collection,
    )

    assert calls == ["iphone case"]
    assert result["query_embedding"] == [0.0] * 1024
    assert len(collection.find_one_calls) == 1
    assert collection.update_one_calls == []


def test_cache_miss_upserts_when_write_enabled() -> None:
    settings = _settings(query_cache_write_enabled=True)
    collection = FakeCollection()

    result = process_query_with_cache(
        "iphone case",
        process_query_fn=_fixture,
        settings=settings,
        collection=collection,
    )
    query_hash = build_query_cache_key("iphone case", settings=settings)

    assert result["original_query"] == "iphone case"
    assert len(collection.update_one_calls) == 1
    assert query_hash in collection.docs
    assert collection.docs[query_hash]["processed_query"]["bm25_search_query_en"] == "iphone case"
    assert collection.docs[query_hash]["usage_count"] == 1


def test_cache_hit_returns_processed_query_without_process_query_call() -> None:
    settings = _settings(query_cache_write_enabled=False)
    cached = _cache_doc("iphone case", settings=settings)
    collection = FakeCollection([cached])

    def fail_process(_raw_query: str) -> dict:
        raise AssertionError("process_query_fn should not be called on a valid cache hit")

    result = process_query_with_cache(
        "iphone case",
        process_query_fn=fail_process,
        settings=settings,
        collection=collection,
    )

    assert result == cached["processed_query"]
    assert collection.update_one_calls == []


def test_cache_hit_touches_usage_only_when_write_enabled() -> None:
    settings = _settings(query_cache_write_enabled=True)
    collection = FakeCollection([_cache_doc("iphone case", settings=settings)])

    result = process_query_with_cache(
        "iphone case",
        process_query_fn=lambda raw_query: _fixture(raw_query),
        settings=settings,
        collection=collection,
    )

    assert result["original_query"] == "iphone case"
    assert len(collection.update_one_calls) == 1
    assert collection.update_one_calls[0][2] is False


def test_stale_or_incomplete_cache_falls_back_to_process_query() -> None:
    settings = _settings()
    query_hash = build_query_cache_key("iphone case", settings=settings)
    stale_cases = [
        {"embedding_model": "old-model"},
        {"query_cache_version": "query_cache_old"},
        {"processed_query": None},
        {"processed_query": {**_fixture("iphone case"), "query_embedding": []}},
    ]

    for patch in stale_cases:
        doc = _cache_doc("iphone case", settings=settings)
        doc["query_hash"] = query_hash
        doc.update(patch)
        collection = FakeCollection([doc])
        calls = []

        result = process_query_with_cache(
            "iphone case",
            process_query_fn=lambda raw_query: calls.append(raw_query) or _fixture(raw_query),
            settings=settings,
            collection=collection,
        )

        assert calls == ["iphone case"]
        assert result["original_query"] == "iphone case"


def test_cache_read_error_falls_back_without_crashing() -> None:
    calls = []
    result = process_query_with_cache(
        "iphone case",
        process_query_fn=lambda raw_query: calls.append(raw_query) or _fixture(raw_query),
        settings=_settings(),
        collection=FakeCollection(read_error=True),
    )

    assert calls == ["iphone case"]
    assert result["original_query"] == "iphone case"


def test_cache_write_error_does_not_crash_search() -> None:
    result = process_query_with_cache(
        "iphone case",
        process_query_fn=_fixture,
        settings=_settings(query_cache_write_enabled=True),
        collection=FakeCollection(write_error=True),
    )

    assert result["original_query"] == "iphone case"
