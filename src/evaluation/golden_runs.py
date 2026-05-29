"""Stable evaluation run profiles for CI, demos, and live regression."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_COMMON_QUERIES = "evaluation/queries/retrieval_queries_seed.json"
_COMMON_JUDGMENTS = "evaluation/judgments/retrieval_judgments_seed.json"
_COMMON_VARIANTS = [
    "hybrid_union",
    "title_only",
    "vector_only",
    "bm25_only",
    "hybrid_no_cold_boost",
]

_PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {
        "profile": "smoke",
        "purpose": "ci_smoke",
        "queries_path": _COMMON_QUERIES,
        "judgments_path": _COMMON_JUDGMENTS,
        "variants": ["hybrid_union", "title_only"],
        "use_fake_results": True,
        "mongodb_live_required": False,
        "output_subdir": "smoke",
        "caveat": "Fast fixture/fake-results smoke check; not production retrieval evidence.",
        "reproducibility_requirements": [
            "input_fingerprints",
            "git_commit",
            "evaluation_schema_version",
            "artifact_contract_version",
        ],
    },
    "judge_demo": {
        "profile": "judge_demo",
        "purpose": "judge_facing_demo",
        "queries_path": _COMMON_QUERIES,
        "judgments_path": _COMMON_JUDGMENTS,
        "variants": _COMMON_VARIANTS,
        "use_fake_results": True,
        "mongodb_live_required": False,
        "output_subdir": "judge_demo",
        "caveat": "Fixed demo dataset; claims remain bounded by judgment provenance and coverage.",
        "reproducibility_requirements": [
            "input_fingerprints",
            "git_commit",
            "evaluation_schema_version",
            "artifact_contract_version",
            "judge_report_pack_manifest",
        ],
    },
    "live_regression": {
        "profile": "live_regression",
        "purpose": "live_regression",
        "queries_path": _COMMON_QUERIES,
        "judgments_path": _COMMON_JUDGMENTS,
        "variants": _COMMON_VARIANTS,
        "use_fake_results": False,
        "mongodb_live_required": True,
        "output_subdir": "live_regression",
        "caveat": "Live MongoDB regression; environment, index, and cache state must be reviewed before claims.",
        "reproducibility_requirements": [
            "input_fingerprints",
            "git_commit",
            "mongodb_source",
            "fixture_source",
            "evaluation_schema_version",
            "artifact_contract_version",
        ],
    },
}


def list_golden_run_profiles() -> list[str]:
    """Return profile names in stable operator-facing order."""
    return list(_PROFILES)


def get_golden_run_profile(name: str) -> dict[str, Any]:
    """Return a copy of a named golden run profile."""
    if name not in _PROFILES:
        raise KeyError(f"Unknown golden run profile: {name}")
    return deepcopy(_PROFILES[name])
