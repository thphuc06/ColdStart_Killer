"""Evaluation data contracts for ColdStart_Killer.

All dataclasses used by the evaluation framework. These are frozen (immutable)
value objects that flow through dataset loading, diagnostics, metrics, and
reporting.

Import safety: this module has NO side effects — no MongoDB, no Ollama,
no file I/O, no environment reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Allowed enum-like values (used by validation)
# ---------------------------------------------------------------------------

VALID_LANGUAGES = frozenset({"en", "vi", "mixed"})

VALID_EXPECTED_STATUSES = frozenset({
    "pass",
    "fail",
    "known_risk",
    "expected_unsupported",
    "skipped_dependency_missing",
    "error",
})

VALID_RESULT_STATUSES = frozenset({"ok", "ok_empty", "failed", "skipped"})

VALID_CLAIM_STATUSES = frozenset({
    "supported",
    "unsupported",
    "needs_more_evidence",
})

VALID_ERROR_TYPES = frozenset({
    "invalid_input_file",
    "invalid_query",
    "invalid_judgment",
    "duplicate_id",
    "stale_fixture_schema",
    "diagnostic_failed",
    "fixture_generation_failed",
    "language_detection_failed",
    "translation_failed",
    "embedding_failed",
    "mongodb_connection_failed",
    "mongodb_write_attempted",
    "vector_index_unavailable",
    "text_index_unavailable",
    "aggregation_failed",
    "variant_unavailable",
    "empty_results",
    "normalization_failed",
    "metrics_failed",
    "reporting_failed",
    "import_side_effect",
    "dependency_missing",
    "unknown_error",
})

VALID_RELEVANCE_VALUES = frozenset({0, 1, 2, 3})

VALID_RELEVANCE_THRESHOLDS = frozenset({1, 2, 3})

VALID_JUDGMENT_SOURCES = frozenset({"ai_assisted", "human_audited", "mixed"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticProbe:
    """A single Layer-1 diagnostic probe for testing query processing."""

    probe_id: str
    raw_query: str
    probe_type: str
    expected_language: str = ""
    expected_filters: dict[str, Any] = field(default_factory=dict)
    expected_status: str = "pass"
    notes: str = ""


@dataclass(frozen=True)
class EvaluationQuery:
    """A retrieval query for Layer-2 evaluation."""

    query_id: str
    raw_query: str
    language: str
    topic: str
    intent_tags: list[str] = field(default_factory=list)
    expected_filters: dict[str, Any] = field(default_factory=dict)
    slices: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class RelevanceJudgment:
    """A human relevance label for a (query, item) pair."""

    query_id: str
    item_id: str
    relevance: int
    reason: str = ""
    labels: list[str] = field(default_factory=list)
    judgment_source: str = "ai_assisted"
    annotator_id: str = ""
    audited_at: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    """A single retrieval result produced by a variant for a query."""

    query_id: str
    variant: str
    rank: int
    item_id: str
    score: float
    title: str = ""
    brand: str = ""
    category_id: str = ""
    price_vnd: int | None = None
    price_bucket: str = ""
    matched_intent: str = ""
    matched_fact: str = ""
    channels: list[str] = field(default_factory=list)
    is_cold_item: bool | None = None
    result_status: str = "ok"
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureRecord:
    """A recorded failure from any stage of the evaluation pipeline."""

    stage: str
    error_type: str
    error: str
    recoverable: bool
    query_id: str = ""
    variant: str = ""
    next_file_to_inspect: str = ""
    next_function_to_inspect: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimStatus:
    """A deterministic claim about system quality with evidence gates."""

    claim: str
    status: str
    evidence: str = ""
    blocker: str = ""


@dataclass(frozen=True)
class RunConfig:
    """Reproducibility record for an evaluation run."""

    run_id: str
    queries_path: str
    judgments_path: str = ""
    output_dir: str = ""
    variants: list[str] = field(default_factory=list)
    top_k: int = 10
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])
    relevance_threshold: int = 2
    use_cached_fixtures: bool = True
    warm_cache: bool | None = None
    mongodb_live: bool | None = None
    created_at: str = ""
    git_commit: str = ""
    plan_version: str = ""
    code_version: str = ""
    python_version: str = ""
    platform: str = ""


@dataclass(frozen=True)
class MetricGateResult:
    """Result of a judgment-coverage or metric-confidence gate check."""

    gate_name: str
    passed: bool
    status: str
    evidence: str = ""
    blocker: str = ""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class ContractValidationError(ValueError):
    """Raised when a data contract validation fails."""


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def validate_diagnostic_probe(probe: DiagnosticProbe) -> DiagnosticProbe:
    """Validate a DiagnosticProbe against contract rules."""
    _require_non_empty(probe.probe_id, "probe_id")
    # raw_query can be empty for edge-case probes (p014, p015 test empty/whitespace)
    if probe.expected_status and probe.expected_status not in VALID_EXPECTED_STATUSES:
        raise ContractValidationError(
            f"expected_status '{probe.expected_status}' not in {sorted(VALID_EXPECTED_STATUSES)}"
        )
    return probe


def validate_evaluation_query(query: EvaluationQuery) -> EvaluationQuery:
    """Validate an EvaluationQuery against contract rules."""
    _require_non_empty(query.query_id, "query_id")
    _require_non_empty(query.raw_query, "raw_query")
    if query.language not in VALID_LANGUAGES:
        raise ContractValidationError(
            f"language '{query.language}' not in {sorted(VALID_LANGUAGES)}"
        )
    return query


def validate_relevance_judgment(judgment: RelevanceJudgment) -> RelevanceJudgment:
    """Validate a RelevanceJudgment against contract rules."""
    _require_non_empty(judgment.query_id, "query_id")
    _require_non_empty(judgment.item_id, "item_id")
    if judgment.relevance not in VALID_RELEVANCE_VALUES:
        raise ContractValidationError(
            f"relevance {judgment.relevance} not in {sorted(VALID_RELEVANCE_VALUES)}"
        )
    if judgment.judgment_source not in VALID_JUDGMENT_SOURCES:
        raise ContractValidationError(
            f"judgment_source '{judgment.judgment_source}' not in {sorted(VALID_JUDGMENT_SOURCES)}"
        )
    return judgment


def validate_run_config(config: RunConfig) -> RunConfig:
    """Validate a RunConfig against contract rules."""
    _require_non_empty(config.run_id, "run_id")
    _require_non_empty(config.queries_path, "queries_path")
    if config.top_k <= 0:
        raise ContractValidationError("top_k must be positive")
    if not config.k_values:
        raise ContractValidationError("k_values must not be empty")
    if any(k <= 0 for k in config.k_values):
        raise ContractValidationError("all k_values must be positive")
    if config.top_k < max(config.k_values):
        raise ContractValidationError(
            f"top_k ({config.top_k}) must be >= max(k_values) ({max(config.k_values)})"
        )
    if config.relevance_threshold not in VALID_RELEVANCE_THRESHOLDS:
        raise ContractValidationError(
            f"relevance_threshold {config.relevance_threshold} not in {sorted(VALID_RELEVANCE_THRESHOLDS)}"
        )
    return config
