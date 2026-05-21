"""Tests for Layer 1 diagnostics — offline, no MongoDB/Ollama required."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.evaluation.contracts import DiagnosticProbe
from src.evaluation.diagnostics import (
    run_diagnostic_probes,
    run_negation_probe,
    summarize_diagnostics,
)


class TestNegationProbe:
    def test_returns_expected_unsupported(self) -> None:
        probe = DiagnosticProbe(
            probe_id="p012", raw_query="not sunscreen",
            probe_type="negation", expected_status="expected_unsupported",
        )
        result = run_negation_probe(probe)
        assert result["status"] == "expected_unsupported"
        assert result["next_file_to_inspect"] == "src/query_processor.py"


class TestSummarizeDiagnostics:
    def test_pass_rate_excludes_non_testable(self) -> None:
        results = [
            {"probe_id": "p1", "status": "pass"},
            {"probe_id": "p2", "status": "fail"},
            {"probe_id": "p3", "status": "known_risk"},
            {"probe_id": "p4", "status": "expected_unsupported"},
            {"probe_id": "p5", "status": "skipped_dependency_missing"},
        ]
        summary = summarize_diagnostics(results)
        assert summary["total_probes"] == 5
        assert summary["testable_probes"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["pass_rate"] == 0.5

    def test_empty_results(self) -> None:
        summary = summarize_diagnostics([])
        assert summary["total_probes"] == 0
        assert summary["pass_rate"] is None


class TestRunDiagnosticProbes:
    def test_unknown_probe_type(self) -> None:
        probes = [
            DiagnosticProbe(probe_id="px", raw_query="test", probe_type="unknown_type"),
        ]
        results = run_diagnostic_probes(probes)
        assert results[0]["status"] == "fail"
        assert "Unknown probe_type" in results[0]["detail"]
