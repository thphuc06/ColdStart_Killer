from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pymongo.errors import OperationFailure


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_item_semantic_neighbors as build_item_semantic_neighbors_script
from src.recommendation.schemas import EMBEDDING_DIM
from src.recommendation.semantic_neighbors import build_item_semantic_neighbors


FIXED_NOW = "2026-01-10T00:00:00+00:00"


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def batch_size(self, _size: int):
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]
        self.bulk_calls = []

    def find(self, filter_doc: dict, projection: dict | None = None):
        def matches(doc: dict) -> bool:
            for key, value in filter_doc.items():
                if isinstance(value, dict) and "$in" in value:
                    if doc.get(key) not in value["$in"]:
                        return False
                    continue
                if doc.get(key) != value:
                    return False
            return True

        matched = []
        for doc in self.docs:
            if not filter_doc or matches(doc):
                if projection:
                    matched.append({key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc})
                else:
                    matched.append(dict(doc))
        return FakeCursor(matched)

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.bulk_calls.extend(operations)
        upserted = 0
        matched = 0
        modified = 0
        for operation in operations:
            filter_doc = operation._filter
            set_doc = dict(operation._doc.get("$set", {}))
            set_on_insert = dict(operation._doc.get("$setOnInsert", {}))
            found = None
            for doc in self.docs:
                if all(doc.get(key) == value for key, value in filter_doc.items()):
                    found = doc
                    break
            if found is None:
                self.docs.append({**set_on_insert, **set_doc})
                upserted += 1
            else:
                matched += 1
                before = dict(found)
                found.update(set_doc)
                if found != before:
                    modified += 1

        class Result:
            upserted_count = upserted
            matched_count = matched
            modified_count = modified

        return Result()


class FakeVectorSearchCollection:
    def __init__(self, results_by_embedding_index: dict[int, list[dict]], failure: Exception | None = None) -> None:
        self.results_by_embedding_index = {
            key: [dict(doc) for doc in docs] for key, docs in results_by_embedding_index.items()
        }
        self.failure = failure
        self.pipelines: list[list[dict]] = []

    def aggregate(self, pipeline, **_kwargs):
        self.pipelines.append(pipeline)
        if self.failure is not None:
            raise self.failure
        vector_stage = pipeline[0]["$vectorSearch"]
        query_vector = vector_stage["queryVector"]
        source_index = max(range(len(query_vector)), key=lambda index: query_vector[index])
        docs = self.results_by_embedding_index.get(source_index, [])
        return FakeCursor(docs[: vector_stage["limit"]])


def _embedding(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _profile(item_id: str, embedding_index: int) -> dict:
    return {
        "_id": item_id,
        "item_id": item_id,
        "item_semantic_embedding": _embedding(embedding_index),
    }


def _item(item_id: str) -> dict:
    return {"_id": item_id, "title_en": f"Item {item_id}"}


def test_build_item_semantic_neighbors_excludes_self_and_sorts_descending() -> None:
    result = build_item_semantic_neighbors(
        item_hype_profiles_collection=FakeCollection([_profile("A", 0)]),
        retrieval_units_collection=FakeVectorSearchCollection(
            {
                0: [
                    {"_id": "self_1", "item_id": "A", "aspect": "function", "score": 0.99},
                    {"_id": "self_2", "item_id": "A", "aspect": "benefit", "score": 0.97},
                    {"_id": "b_1", "item_id": "B", "aspect": "constraint", "score": 0.92},
                    {"_id": "b_2", "item_id": "B", "aspect": "style", "score": 0.82},
                    {"_id": "c_1", "item_id": "C", "aspect": "function", "score": 0.88},
                    {"_id": "c_2", "item_id": "C", "aspect": "occasion", "score": 0.84},
                    {"_id": "c_3", "item_id": "C", "aspect": "persona", "score": 0.83},
                ]
            }
        ),
        items_collection=FakeCollection([_item("A"), _item("B"), _item("C")]),
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["stats"]["self_hits_excluded"] == 2
    assert result["stats"]["neighbor_docs_built"] == 1

    doc = result["sample_neighbors"][0]
    assert doc["item_id"] == "A"
    assert doc["neighbor_count"] == 2
    neighbors = doc["neighbors"]
    assert [neighbor["neighbor_item_id"] for neighbor in neighbors] == ["B", "C"]
    assert neighbors[0]["neighbor_score"] > neighbors[1]["neighbor_score"]
    assert neighbors[0]["matched_unit_ids"] == ["b_1", "b_2"]
    assert neighbors[0]["matched_aspects"] == ["constraint", "style"]


def test_build_item_semantic_neighbors_caps_neighbors_and_uses_idempotent_upsert() -> None:
    output = FakeCollection([])
    result = build_item_semantic_neighbors(
        item_hype_profiles_collection=FakeCollection([_profile("A", 0)]),
        retrieval_units_collection=FakeVectorSearchCollection(
            {
                0: [
                    {"_id": "b_1", "item_id": "B", "aspect": "constraint", "score": 0.95},
                    {"_id": "c_1", "item_id": "C", "aspect": "benefit", "score": 0.90},
                    {"_id": "d_1", "item_id": "D", "aspect": "style", "score": 0.85},
                ]
            }
        ),
        items_collection=FakeCollection([_item("A"), _item("B"), _item("C"), _item("D")]),
        item_semantic_neighbors_collection=output,
        write=True,
        top_neighbors_per_item=2,
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is True
    assert result["stats"]["source_profiles_written"] == 1
    assert len(output.bulk_calls) == 1
    operation = output.bulk_calls[0]
    assert operation._filter == {"_id": "A"}
    assert operation._doc["$setOnInsert"] == {"_id": "A"}
    assert "_id" not in operation._doc["$set"]
    assert len(output.docs[0]["neighbors"]) == 2


def test_build_item_semantic_neighbors_reports_unavailable_without_partial_write() -> None:
    output = FakeCollection([])
    result = build_item_semantic_neighbors(
        item_hype_profiles_collection=FakeCollection([_profile("A", 0)]),
        retrieval_units_collection=FakeVectorSearchCollection({}, failure=OperationFailure("vector search unavailable", code=8000)),
        items_collection=FakeCollection([_item("A")]),
        item_semantic_neighbors_collection=output,
        write=True,
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is False
    assert result["status"] == "semantic_neighbors_unavailable"
    assert result["semantic_neighbors_unavailable"] is True
    assert result["stats"]["vector_search_failures"] == 1
    assert output.bulk_calls == []
    assert output.docs == []


def test_phase8_script_dry_run_does_not_write_neighbors(monkeypatch, capsys) -> None:
    item_hype_profiles = FakeCollection([_profile("A", 0)])
    retrieval_units = FakeVectorSearchCollection(
        {0: [{"_id": "b_1", "item_id": "B", "aspect": "constraint", "score": 0.95}]}
    )
    items = FakeCollection([_item("A"), _item("B")])
    neighbors = FakeCollection([])

    monkeypatch.setattr(build_item_semantic_neighbors_script, "get_item_hype_profiles_collection", lambda: item_hype_profiles)
    monkeypatch.setattr(build_item_semantic_neighbors_script, "get_retrieval_units_collection", lambda: retrieval_units)
    monkeypatch.setattr(build_item_semantic_neighbors_script, "get_items_collection", lambda: items)
    monkeypatch.setattr(build_item_semantic_neighbors_script, "get_item_semantic_neighbors_collection", lambda: neighbors)

    exit_code = build_item_semantic_neighbors_script.main(["--dry-run", "--limit", "1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "dry-run"' in captured.out
    assert neighbors.docs == []


def test_build_item_semantic_neighbors_validates_arguments() -> None:
    profiles = FakeCollection([])
    retrieval_units = FakeVectorSearchCollection({})
    items = FakeCollection([])

    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            limit_profiles=0,
        )
    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            batch_size=0,
        )
    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            retrieval_hit_limit=0,
        )
    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            top_neighbors_per_item=0,
        )
    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            retrieval_hit_limit=10,
            num_candidates=5,
        )
    with pytest.raises(ValueError):
        build_item_semantic_neighbors(
            item_hype_profiles_collection=profiles,
            retrieval_units_collection=retrieval_units,
            items_collection=items,
            write=True,
        )