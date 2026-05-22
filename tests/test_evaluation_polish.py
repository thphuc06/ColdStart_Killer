"""Tests for evaluation polish/reporting helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_explanation_quality_stats() -> None:
    from src.evaluation.explanation_check import check_explanation_quality

    stats = check_explanation_quality([
        {"matched_intent": "intent", "matched_fact": "fact"},
        {"matched_intent": "intent", "matched_fact": ""},
        {"matched_intent": "", "matched_fact": ""},
    ])

    assert stats == {
        "total_results": 3,
        "has_matched_intent": 2,
        "has_matched_fact": 1,
        "has_both_explanations": 1,
        "has_no_explanation": 1,
        "intent_coverage": round(2 / 3, 4),
        "fact_coverage": round(1 / 3, 4),
        "full_explanation_coverage": round(1 / 3, 4),
    }


def test_notebook_explains_na_metrics() -> None:
    notebook = ROOT / "notebooks" / "05_evaluation_retrieval_quality.ipynb"
    text = notebook.read_text(encoding="utf-8")
    assert "About N/A Metrics" in text
    assert "No relevance judgments yet" in text
    assert "How to fix N/A metrics" in text
