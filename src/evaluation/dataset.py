"""Dataset loading for evaluation queries, probes, and judgments.

Import safety: no side effects — no MongoDB, no Ollama, no file writes.
All I/O happens through explicit function calls only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    ContractValidationError,
    DiagnosticProbe,
    EvaluationQuery,
    RelevanceJudgment,
    validate_diagnostic_probe,
    validate_evaluation_query,
    validate_relevance_judgment,
)


def _load_json(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSON file and return a list of dicts."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.suffix == ".json":
        raise ValueError(f"Expected .json file, got: {p.suffix}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ContractValidationError(f"Expected a JSON array in {p}, got {type(data).__name__}")
    return data


def load_diagnostic_probes(path: str | Path) -> list[DiagnosticProbe]:
    """Load and validate diagnostic probes from a JSON file.

    Raises ContractValidationError on invalid data or duplicate probe_ids.
    """
    raw = _load_json(path)
    probes: list[DiagnosticProbe] = []
    seen_ids: set[str] = set()

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ContractValidationError(f"Probe at index {i} is not a dict")
        try:
            probe = DiagnosticProbe(
                probe_id=item.get("probe_id", ""),
                raw_query=item.get("raw_query", ""),
                probe_type=item.get("probe_type", ""),
                expected_language=item.get("expected_language", ""),
                expected_filters=item.get("expected_filters", {}),
                expected_status=item.get("expected_status", "pass"),
                notes=item.get("notes", ""),
            )
            validate_diagnostic_probe(probe)
        except (ContractValidationError, TypeError) as exc:
            raise ContractValidationError(f"Probe at index {i}: {exc}") from exc

        if probe.probe_id in seen_ids:
            raise ContractValidationError(f"Duplicate probe_id: {probe.probe_id}")
        seen_ids.add(probe.probe_id)
        probes.append(probe)

    return probes


def load_eval_queries(path: str | Path) -> list[EvaluationQuery]:
    """Load and validate evaluation queries from a JSON file.

    Raises ContractValidationError on invalid data or duplicate query_ids.
    """
    raw = _load_json(path)
    queries: list[EvaluationQuery] = []
    seen_ids: set[str] = set()

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ContractValidationError(f"Query at index {i} is not a dict")
        try:
            query = EvaluationQuery(
                query_id=item.get("query_id", ""),
                raw_query=item.get("raw_query", ""),
                language=item.get("language", ""),
                topic=item.get("topic", ""),
                intent_tags=item.get("intent_tags", []),
                expected_filters=item.get("expected_filters", {}),
                slices=item.get("slices", []),
                notes=item.get("notes", ""),
            )
            validate_evaluation_query(query)
        except (ContractValidationError, TypeError) as exc:
            raise ContractValidationError(f"Query at index {i}: {exc}") from exc

        if query.query_id in seen_ids:
            raise ContractValidationError(f"Duplicate query_id: {query.query_id}")
        seen_ids.add(query.query_id)
        queries.append(query)

    return queries


def load_relevance_judgments(path: str | Path) -> list[RelevanceJudgment]:
    """Load and validate relevance judgments from a JSON file.

    Raises ContractValidationError on invalid data or duplicate (query_id, item_id).
    An empty array is valid (pre-labeling state).
    """
    raw = _load_json(path)
    judgments: list[RelevanceJudgment] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ContractValidationError(f"Judgment at index {i} is not a dict")
        try:
            judgment = RelevanceJudgment(
                query_id=item.get("query_id", ""),
                item_id=item.get("item_id", ""),
                relevance=item.get("relevance", -1),
                reason=item.get("reason", ""),
                labels=item.get("labels", []),
                judgment_source=item.get("judgment_source", "ai_assisted"),
                annotator_id=item.get("annotator_id", ""),
                audited_at=item.get("audited_at", ""),
            )
            validate_relevance_judgment(judgment)
        except (ContractValidationError, TypeError) as exc:
            raise ContractValidationError(f"Judgment at index {i}: {exc}") from exc

        pair = (judgment.query_id, judgment.item_id)
        if pair in seen_pairs:
            raise ContractValidationError(
                f"Duplicate (query_id, item_id): ({judgment.query_id}, {judgment.item_id})"
            )
        seen_pairs.add(pair)
        judgments.append(judgment)

    return judgments


def judgments_by_query(judgments: list[RelevanceJudgment]) -> dict[str, dict[str, int]]:
    """Index judgments by query_id -> {item_id: relevance}.

    Returns a dict where keys are query_ids and values are dicts
    mapping item_id to relevance score.
    """
    result: dict[str, dict[str, int]] = {}
    for j in judgments:
        result.setdefault(j.query_id, {})[j.item_id] = j.relevance
    return result
