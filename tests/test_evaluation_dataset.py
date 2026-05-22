"""Tests for evaluation contracts and dataset loading."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.evaluation.contracts import (
    ContractValidationError,
    DiagnosticProbe,
    EvaluationQuery,
    EvaluationResult,
    RelevanceJudgment,
    RunConfig,
    validate_diagnostic_probe,
    validate_evaluation_query,
    validate_relevance_judgment,
    validate_run_config,
)
from src.evaluation.dataset import (
    judgments_by_query,
    load_diagnostic_probes,
    load_eval_queries,
    load_relevance_judgments,
)


# ---------- Contract Validation ----------

class TestDiagnosticProbeValidation:
    def test_valid_probe(self) -> None:
        probe = DiagnosticProbe(probe_id="p001", raw_query="test", probe_type="language_detection")
        assert validate_diagnostic_probe(probe) == probe

    def test_empty_probe_id_fails(self) -> None:
        with pytest.raises(ContractValidationError, match="probe_id"):
            validate_diagnostic_probe(DiagnosticProbe(probe_id="", raw_query="test", probe_type="x"))

    def test_invalid_expected_status_fails(self) -> None:
        with pytest.raises(ContractValidationError, match="expected_status"):
            validate_diagnostic_probe(
                DiagnosticProbe(probe_id="p1", raw_query="x", probe_type="x", expected_status="invalid")
            )


class TestEvaluationQueryValidation:
    def test_valid_query(self) -> None:
        q = EvaluationQuery(query_id="q001", raw_query="test query", language="en", topic="skincare")
        assert validate_evaluation_query(q) == q

    def test_invalid_language_fails(self) -> None:
        with pytest.raises(ContractValidationError, match="language"):
            validate_evaluation_query(
                EvaluationQuery(query_id="q1", raw_query="test", language="fr", topic="x")
            )

    def test_empty_raw_query_fails(self) -> None:
        with pytest.raises(ContractValidationError, match="raw_query"):
            validate_evaluation_query(
                EvaluationQuery(query_id="q1", raw_query="", language="en", topic="x")
            )


class TestRelevanceJudgmentValidation:
    def test_valid_judgment(self) -> None:
        j = RelevanceJudgment(query_id="q001", item_id="B001", relevance=3)
        assert validate_relevance_judgment(j) == j

    def test_invalid_relevance_fails(self) -> None:
        with pytest.raises(ContractValidationError, match="relevance"):
            validate_relevance_judgment(
                RelevanceJudgment(query_id="q1", item_id="B1", relevance=5)
            )


class TestRunConfigValidation:
    def test_valid_config(self) -> None:
        c = RunConfig(run_id="test", queries_path="q.json")
        assert validate_run_config(c) == c

    def test_top_k_must_be_positive(self) -> None:
        with pytest.raises(ContractValidationError, match="top_k"):
            validate_run_config(RunConfig(run_id="t", queries_path="q.json", top_k=0))

    def test_top_k_must_exceed_max_k_values(self) -> None:
        with pytest.raises(ContractValidationError, match="top_k"):
            validate_run_config(
                RunConfig(run_id="t", queries_path="q.json", top_k=5, k_values=[1, 3, 10])
            )

    def test_invalid_relevance_threshold(self) -> None:
        with pytest.raises(ContractValidationError, match="relevance_threshold"):
            validate_run_config(
                RunConfig(run_id="t", queries_path="q.json", relevance_threshold=0)
            )


# ---------- Dataset Loading ----------

class TestLoadDiagnosticProbes:
    def test_load_actual_probes_file(self) -> None:
        path = ROOT / "evaluation" / "queries" / "diagnostic_probes.json"
        if path.exists():
            probes = load_diagnostic_probes(path)
            assert len(probes) == 20
            assert probes[0].probe_id == "p001"

    def test_duplicate_probe_id_fails(self) -> None:
        data = [
            {"probe_id": "p1", "raw_query": "test", "probe_type": "language_detection"},
            {"probe_id": "p1", "raw_query": "test2", "probe_type": "language_detection"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with pytest.raises(ContractValidationError, match="Duplicate probe_id"):
                load_diagnostic_probes(f.name)

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_diagnostic_probes("/nonexistent/file.json")


class TestLoadEvalQueries:
    def test_load_actual_queries_file(self) -> None:
        path = ROOT / "evaluation" / "queries" / "retrieval_queries_seed.json"
        if path.exists():
            queries = load_eval_queries(path)
            assert len(queries) == 50
            assert queries[0].query_id == "q001"

    def test_duplicate_query_id_fails(self) -> None:
        data = [
            {"query_id": "q1", "raw_query": "test", "language": "en", "topic": "x"},
            {"query_id": "q1", "raw_query": "test2", "language": "en", "topic": "x"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with pytest.raises(ContractValidationError, match="Duplicate query_id"):
                load_eval_queries(f.name)


class TestLoadRelevanceJudgments:
    def test_empty_array_is_valid(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([], f)
            f.flush()
            judgments = load_relevance_judgments(f.name)
            assert judgments == []

    def test_duplicate_pair_fails(self) -> None:
        data = [
            {"query_id": "q1", "item_id": "B1", "relevance": 3},
            {"query_id": "q1", "item_id": "B1", "relevance": 2},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            with pytest.raises(ContractValidationError, match="Duplicate"):
                load_relevance_judgments(f.name)


class TestJudgmentsByQuery:
    def test_basic_indexing(self) -> None:
        judgments = [
            RelevanceJudgment(query_id="q1", item_id="B1", relevance=3),
            RelevanceJudgment(query_id="q1", item_id="B2", relevance=1),
            RelevanceJudgment(query_id="q2", item_id="B1", relevance=2),
        ]
        indexed = judgments_by_query(judgments)
        assert indexed == {
            "q1": {"B1": 3, "B2": 1},
            "q2": {"B1": 2},
        }

    def test_empty_list(self) -> None:
        assert judgments_by_query([]) == {}
