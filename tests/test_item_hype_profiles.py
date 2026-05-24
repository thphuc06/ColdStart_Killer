from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.item_hype_profiles import (
    ASPECT_WEIGHTS,
    build_item_hype_profiles,
    build_profile_from_hype_units,
)
from src.recommendation.schemas import EMBEDDING_DIM


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def test_build_profile_from_hype_units_uses_weighted_normalized_centroid() -> None:
    units = [
        {
            "_id": "ru_constraint",
            "item_id": "B001",
            "embedding": _unit_vector(0),
            "confidence": 1.0,
            "aspect": "constraint",
            "category_id": "all_beauty",
            "price_bucket": "100k_300k",
        },
        {
            "_id": "ru_style",
            "item_id": "B001",
            "embedding": _unit_vector(1),
            "confidence": 0.5,
            "aspect": "style",
            "category_id": "all_beauty",
            "price_bucket": "100k_300k",
        },
    ]

    profile, stats = build_profile_from_hype_units("B001", units, updated_at="now")

    assert profile is not None
    assert stats.profiles_built == 1
    assert stats.valid_units == 2
    expected = np.asarray(
        [ASPECT_WEIGHTS["constraint"], 0.5 * ASPECT_WEIGHTS["style"]] + [0.0] * (EMBEDDING_DIM - 2),
        dtype=np.float64,
    )
    expected = expected / np.linalg.norm(expected)
    actual = np.asarray(profile["item_semantic_embedding"])
    assert actual.shape == (EMBEDDING_DIM,)
    assert math.isclose(float(np.linalg.norm(actual)), 1.0, abs_tol=1e-9)
    assert np.allclose(actual[:2], expected[:2])
    assert profile["_id"] == "B001"
    assert profile["top_hype_unit_ids"] == ["ru_constraint", "ru_style"]
    assert profile["top_aspects"] == ["constraint", "style"]
    assert profile["num_hype_units"] == 2


def test_build_profile_from_hype_units_skips_invalid_embeddings_and_weights() -> None:
    bad_nan = _unit_vector(0)
    bad_nan[0] = float("nan")
    units = [
        {"_id": "bad_dim", "embedding": [0.0] * 10, "confidence": 1.0, "aspect": "function"},
        {"_id": "bad_nan", "embedding": bad_nan, "confidence": 1.0, "aspect": "function"},
        {"_id": "zero_weight", "embedding": _unit_vector(0), "confidence": 0.0, "aspect": "function"},
        {"_id": "valid", "embedding": _unit_vector(1), "confidence": 0.7, "aspect": "persona"},
    ]

    profile, stats = build_profile_from_hype_units("B001", units)

    assert profile is not None
    assert stats.units_seen == 4
    assert stats.invalid_dimension_units == 1
    assert stats.non_finite_units == 1
    assert stats.non_positive_weight_units == 1
    assert stats.valid_units == 1
    assert profile["top_hype_unit_ids"] == ["valid"]


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs

    def sort(self, sort_spec):
        field, direction = sort_spec[0]
        reverse = direction < 0
        self.docs = sorted(self.docs, key=lambda doc: doc.get(field, ""), reverse=reverse)
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeRetrievalUnitsCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs
        self.find_filter = None
        self.find_projection = None

    def find(self, filter_doc, projection):
        self.find_filter = filter_doc
        self.find_projection = projection
        docs = [doc for doc in self.docs if doc.get("unit_type") == filter_doc["unit_type"]]
        return FakeCursor(docs)


class FakeItemsCollection:
    def __init__(self, docs: dict[str, dict]) -> None:
        self.docs = docs
        self.lookups: list[str] = []

    def find_one(self, filter_doc, projection):
        _ = projection
        item_id = filter_doc["_id"]
        self.lookups.append(item_id)
        return self.docs.get(item_id)


class FakeBulkResult:
    upserted_count = 2
    modified_count = 0
    matched_count = 0


class FakeOutputCollection:
    def __init__(self) -> None:
        self.operations = []

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.operations.extend(operations)
        return FakeBulkResult()


def test_build_item_hype_profiles_dry_run_does_not_write_and_limits_by_item() -> None:
    retrieval_units = FakeRetrievalUnitsCollection(
        [
            {
                "_id": "ru_b2",
                "item_id": "B002",
                "unit_type": "hype_question",
                "embedding": _unit_vector(2),
                "confidence": 0.9,
                "aspect": "function",
            },
            {
                "_id": "ru_b1",
                "item_id": "B001",
                "unit_type": "hype_question",
                "embedding": _unit_vector(1),
                "confidence": 0.8,
                "aspect": "persona",
            },
        ]
    )
    items = FakeItemsCollection({"B001": {"category_id": "all_beauty", "price_bucket": "100k_300k"}})
    output = FakeOutputCollection()

    result = build_item_hype_profiles(
        retrieval_units_collection=retrieval_units,
        items_collection=items,
        item_hype_profiles_collection=output,
        limit_profiles=1,
        write=False,
    )

    assert result["ok"] is True
    assert result["write"] is False
    assert result["stats"]["profiles_built"] == 1
    assert result["sample_profiles"][0]["item_id"] == "B001"
    assert result["sample_profiles"][0]["category_id"] == "all_beauty"
    assert output.operations == []
    assert retrieval_units.find_filter == {"unit_type": "hype_question"}


def test_build_item_hype_profiles_write_uses_idempotent_upsert_without_setting_id() -> None:
    retrieval_units = FakeRetrievalUnitsCollection(
        [
            {
                "_id": "ru_b1",
                "item_id": "B001",
                "unit_type": "hype_question",
                "embedding": _unit_vector(0),
                "confidence": 1.0,
                "aspect": "function",
            },
            {
                "_id": "ru_b2",
                "item_id": "B002",
                "unit_type": "hype_question",
                "embedding": _unit_vector(1),
                "confidence": 1.0,
                "aspect": "function",
            },
        ]
    )
    output = FakeOutputCollection()

    result = build_item_hype_profiles(
        retrieval_units_collection=retrieval_units,
        item_hype_profiles_collection=output,
        write=True,
        batch_size=10,
    )

    assert result["ok"] is True
    assert result["stats"]["profiles_built"] == 2
    assert result["stats"]["bulk_write_batches"] == 1
    assert len(output.operations) == 2
    first_op = output.operations[0]
    assert first_op._filter == {"_id": "B001"}
    assert first_op._doc["$setOnInsert"] == {"_id": "B001"}
    assert "_id" not in first_op._doc["$set"]


def test_build_item_hype_profiles_validates_limit_and_batch_size() -> None:
    retrieval_units = FakeRetrievalUnitsCollection([])
    with pytest.raises(ValueError):
        build_item_hype_profiles(retrieval_units_collection=retrieval_units, limit_profiles=0)
    with pytest.raises(ValueError):
        build_item_hype_profiles(retrieval_units_collection=retrieval_units, batch_size=0)
    with pytest.raises(ValueError):
        build_item_hype_profiles(retrieval_units_collection=retrieval_units, write=True)
