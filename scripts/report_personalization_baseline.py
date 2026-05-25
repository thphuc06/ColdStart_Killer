from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.routes_debug import get_debug_user
from src.behavior.intent_hygiene import (
    is_fact_like_label,
    is_generic_interest_label,
    is_uuid_like_label,
    is_valid_interest_label,
    normalize_interest_label,
)
from src.config import get_settings
from src.mongodb import get_user_profiles_collection
from src.recommendation.candidate_sources import load_user_signals
from src.recommendation.homepage_feed import get_homepage_feed
from src.utils import utc_now_iso


DEFAULT_USER_ID = "u_api_5ea7eb5ac87d4abe"
DEFAULT_SESSION_ID = "sess_phuc_demo_baseline"
DEFAULT_TOP_K = 10
DEFAULT_SIGNALS_LIMIT = 10
SPEC_EXPLANATION_MARKERS = ("amoled", "touchscreen", "16m colors")


class _InMemoryRecommendationLogsCollection:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def bulk_write(self, operations, ordered: bool = False):
        assert ordered is False
        inserted = 0
        matched = 0
        for operation in operations:
            filter_doc = getattr(operation, "_filter", {})
            set_on_insert = dict(getattr(operation, "_doc", {}).get("$setOnInsert", {}))
            existing = None
            for doc in self.docs:
                if all(doc.get(key) == value for key, value in filter_doc.items()):
                    existing = doc
                    break
            if existing is None:
                self.docs.append(set_on_insert)
                inserted += 1
            else:
                matched += 1

        class Result:
            upserted_count = inserted
            matched_count = matched
            modified_count = 0

        return Result()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only personalization baseline report.")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="Internal user_id_hash to audit.")
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help="Synthetic session id for the in-memory homepage snapshot.",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Number of homepage items to include.")
    parser.add_argument(
        "--signals-limit",
        type=int,
        default=DEFAULT_SIGNALS_LIMIT,
        help="Number of user signals to sample.",
    )
    parser.add_argument("--out", default=None, help="Optional output directory for JSON and Markdown artifacts.")
    return parser.parse_args(argv)


def _profile_label_counters(profile_doc: dict[str, Any] | None, *, max_label_length: int) -> dict[str, Any]:
    counters = {
        "uuid_label_count": 0,
        "fact_label_count": 0,
        "generic_label_count": 0,
        "invalid_label_count": 0,
        "sample_invalid_labels": [],
    }
    interest_vectors = profile_doc.get("interest_vectors") if isinstance(profile_doc, dict) else []
    if not isinstance(interest_vectors, list):
        return counters

    for interest in interest_vectors:
        if not isinstance(interest, dict):
            continue
        label = normalize_interest_label(interest.get("label"))
        if not label:
            continue
        invalid = False
        if is_uuid_like_label(label):
            counters["uuid_label_count"] += 1
            invalid = True
        if is_fact_like_label(label, max_length=max_label_length):
            counters["fact_label_count"] += 1
            invalid = True
        if is_generic_interest_label(label):
            counters["generic_label_count"] += 1
            invalid = True
        if not is_valid_interest_label(label, max_length=max_label_length):
            counters["invalid_label_count"] += 1
            invalid = True
        if invalid and len(counters["sample_invalid_labels"]) < 5:
            counters["sample_invalid_labels"].append(label)
    return counters


def _explanation_audit(items: list[dict[str, Any]], *, max_label_length: int) -> dict[str, Any]:
    invalid_profile_reason_count = 0
    contaminated_explanation_count = 0
    failures: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        debug = item.get("debug") if isinstance(item.get("debug"), dict) else {}
        profile_label = normalize_interest_label(debug.get("profile_interest_label"))
        explanations = [str(value) for value in item.get("explanations", []) if str(value).strip()]

        if profile_label and not is_valid_interest_label(profile_label, max_length=max_label_length):
            invalid_profile_reason_count += 1
            if len(failures) < 5:
                failures.append(
                    {
                        "item_id": str(item.get("item_id") or ""),
                        "kind": "invalid_profile_label",
                        "value": profile_label,
                    }
                )

        contaminated = False
        for explanation in explanations:
            lowered = explanation.casefold()
            if any(marker in lowered for marker in SPEC_EXPLANATION_MARKERS) or any(
                is_uuid_like_label(token) for token in explanation.split()
            ):
                contaminated = True
                break
        if contaminated:
            contaminated_explanation_count += 1
            if len(failures) < 5:
                failures.append(
                    {
                        "item_id": str(item.get("item_id") or ""),
                        "kind": "contaminated_explanation",
                        "value": explanations,
                    }
                )

    return {
        "invalid_profile_reason_count": invalid_profile_reason_count,
        "contaminated_explanation_count": contaminated_explanation_count,
        "profile_explanation_audit_failures": invalid_profile_reason_count + contaminated_explanation_count,
        "sample_explanation_failures": failures,
    }


def build_personalization_baseline_report(
    *,
    user_id: str,
    session_id: str,
    top_k: int = DEFAULT_TOP_K,
    signals_limit: int = DEFAULT_SIGNALS_LIMIT,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if signals_limit <= 0:
        raise ValueError("signals_limit must be positive")

    settings = get_settings()
    profile_doc = get_user_profiles_collection().find_one({"user_id_hash": user_id}, {"_id": 0}) or {}
    debug = get_debug_user(user_id)
    signals = load_user_signals(user_id, limit=signals_limit)
    in_memory_logs = _InMemoryRecommendationLogsCollection()
    feed = get_homepage_feed(
        user_id,
        session_id,
        top_k=top_k,
        recommendation_logs_collection=in_memory_logs,
    )

    label_counters = _profile_label_counters(profile_doc, max_label_length=settings.profile_label_max_length)
    explanation_counters = _explanation_audit(feed.get("items", []), max_label_length=settings.profile_label_max_length)
    counters = {**label_counters, **explanation_counters}

    return {
        "generated_at": utc_now_iso(),
        "user_id": user_id,
        "session_id": session_id,
        "freshness": debug.get("freshness", {}),
        "counters": counters,
        "profile": {
            "profile_status": str(profile_doc.get("profile_status") or ""),
            "interest_labels": [
                normalize_interest_label(interest.get("label"))
                for interest in profile_doc.get("interest_vectors", [])
                if isinstance(interest, dict) and normalize_interest_label(interest.get("label"))
            ],
            "interest_vectors": [
                {
                    "label": normalize_interest_label(interest.get("label")),
                    "top_intents": [
                        normalize_interest_label(value)
                        for value in interest.get("top_intents", [])
                        if normalize_interest_label(value)
                    ],
                    "categories": list(interest.get("categories", [])),
                    "top_item_ids": list(interest.get("top_item_ids", [])),
                }
                for interest in profile_doc.get("interest_vectors", [])
                if isinstance(interest, dict)
            ],
            "intent_affinity": list(profile_doc.get("intent_affinity", []))[:10],
            "negative_preferences": dict(profile_doc.get("negative_preferences", {})),
        },
        "signals": {
            "count": len(signals),
            "seed_eligible_count": sum(1 for signal in signals if signal.get("seed_eligible")),
            "items": [
                {
                    "item_id": str(signal.get("item_id") or ""),
                    "seed_eligible": bool(signal.get("seed_eligible")),
                    "intent_tier": str(signal.get("intent_tier") or ""),
                    "contributions": dict(signal.get("contributions") or {}),
                    "reason_intents": [
                        str(reason.get("intent") or "")
                        for reason in signal.get("reason_scores", [])
                        if isinstance(reason, dict) and str(reason.get("intent") or "")
                    ],
                }
                for signal in signals
            ],
        },
        "homepage": {
            "request_id": str(feed.get("request_id") or ""),
            "snapshot": dict(feed.get("snapshot") or {}),
            "items": [
                {
                    "item_id": str(item.get("item_id") or ""),
                    "reason_badges": list(item.get("reason_badges", [])),
                    "explanations": list(item.get("explanations", [])),
                    "profile_interest_label": normalize_interest_label(
                        (item.get("debug") or {}).get("profile_interest_label")
                        if isinstance(item.get("debug"), dict)
                        else ""
                    ),
                }
                for item in feed.get("items", [])
            ],
        },
    }


def _report_markdown(report: dict[str, Any]) -> str:
    counters = report.get("counters", {}) if isinstance(report.get("counters"), dict) else {}
    freshness = report.get("freshness", {}) if isinstance(report.get("freshness"), dict) else {}
    lines = [
        "# Personalization Baseline Report",
        "",
        f"- Generated at: {report.get('generated_at', '')}",
        f"- User: {report.get('user_id', '')}",
        f"- Freshness state: {freshness.get('state', '')}",
        f"- Pending events: {freshness.get('pending_event_count', 0)}",
        f"- UUID labels: {counters.get('uuid_label_count', 0)}",
        f"- Fact-like labels: {counters.get('fact_label_count', 0)}",
        f"- Generic labels: {counters.get('generic_label_count', 0)}",
        f"- Explanation audit failures: {counters.get('profile_explanation_audit_failures', 0)}",
        "",
        "## Interest Labels",
    ]
    for label in report.get("profile", {}).get("interest_labels", []):
        lines.append(f"- {label}")
    if not report.get("profile", {}).get("interest_labels"):
        lines.append("- none")
    lines.append("")
    lines.append("## Homepage Sample")
    for item in report.get("homepage", {}).get("items", [])[:5]:
        lines.append(f"- {item.get('item_id', '')}: {', '.join(item.get('reason_badges', []))}")
        for explanation in item.get("explanations", [])[:3]:
            lines.append(f"  - {explanation}")
    if not report.get("homepage", {}).get("items"):
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_report_artifacts(report: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "personalization_baseline.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (out_dir / "personalization_baseline.md").write_text(_report_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_personalization_baseline_report(
        user_id=args.user_id,
        session_id=args.session_id,
        top_k=args.top_k,
        signals_limit=args.signals_limit,
    )
    if args.out:
        write_report_artifacts(report, Path(args.out))
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())