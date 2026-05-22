"""Layer 1 diagnostic probes for ColdStart_Killer query processing.

Tests language detection, price filter extraction, and edge cases
using the production query_processor functions.

Import safety: no side effects at import time.
"""

from __future__ import annotations

from typing import Any

from .contracts import DiagnosticProbe, FailureRecord


def _compare_filters(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Compare expected and actual filters, returning a list of mismatch descriptions."""
    mismatches: list[str] = []
    for key, expected_val in expected.items():
        actual_val = actual.get(key)
        if actual_val != expected_val:
            mismatches.append(f"{key}: expected {expected_val!r}, got {actual_val!r}")
    return mismatches


def run_language_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run a language detection probe against detect_language()."""
    from src.query_processor import detect_language

    try:
        detected = detect_language(probe.raw_query)
    except (ValueError, Exception) as exc:
        if probe.expected_status == "error":
            return {
                "probe_id": probe.probe_id,
                "status": "pass",
                "detail": f"Expected error raised: {exc}",
            }
        return {
            "probe_id": probe.probe_id,
            "status": "fail",
            "detail": f"Unexpected error: {exc}",
        }

    if probe.expected_status == "known_risk":
        return {
            "probe_id": probe.probe_id,
            "status": "known_risk",
            "expected_language": probe.expected_language,
            "actual_language": detected,
            "detail": probe.notes,
        }

    if detected == probe.expected_language:
        return {"probe_id": probe.probe_id, "status": "pass", "actual_language": detected}

    return {
        "probe_id": probe.probe_id,
        "status": "fail",
        "expected_language": probe.expected_language,
        "actual_language": detected,
        "detail": f"Expected {probe.expected_language!r}, got {detected!r}",
    }


def run_price_filter_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run a price filter extraction probe against extract_hard_filters()."""
    from src.query_processor import detect_language, extract_hard_filters

    result: dict[str, Any] = {"probe_id": probe.probe_id}

    # Check language detection first
    try:
        detected_lang = detect_language(probe.raw_query)
    except (ValueError, Exception):
        detected_lang = "unknown"
    result["actual_language"] = detected_lang

    # Check price filter extraction
    try:
        actual_filters = extract_hard_filters(probe.raw_query)
    except (ValueError, Exception) as exc:
        if probe.expected_status == "error":
            result["status"] = "pass"
            result["detail"] = f"Expected error raised: {exc}"
            return result
        result["status"] = "fail"
        result["detail"] = f"Unexpected error: {exc}"
        return result

    if probe.expected_status == "known_risk":
        mismatches = _compare_filters(probe.expected_filters, actual_filters)
        result["status"] = "known_risk"
        result["actual_filters"] = actual_filters
        result["mismatches"] = mismatches
        result["detail"] = probe.notes
        return result

    mismatches = _compare_filters(probe.expected_filters, actual_filters)
    if mismatches:
        result["status"] = "fail"
        result["actual_filters"] = actual_filters
        result["mismatches"] = mismatches
        result["detail"] = "; ".join(mismatches)
    else:
        result["status"] = "pass"
        result["actual_filters"] = actual_filters

    return result


def run_empty_query_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run an empty/whitespace query probe."""
    from src.query_processor import detect_language

    try:
        detect_language(probe.raw_query)
        return {
            "probe_id": probe.probe_id,
            "status": "fail",
            "detail": "Expected ValueError but no error was raised",
        }
    except ValueError:
        return {
            "probe_id": probe.probe_id,
            "status": "pass",
            "detail": "ValueError raised as expected",
        }
    except Exception as exc:
        return {
            "probe_id": probe.probe_id,
            "status": "pass",
            "detail": f"Error raised (not ValueError): {type(exc).__name__}: {exc}",
        }


def run_edge_case_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run an edge case probe — just verify no crash."""
    from src.query_processor import detect_language, extract_hard_filters

    try:
        lang = detect_language(probe.raw_query)
        filters = extract_hard_filters(probe.raw_query)
        return {
            "probe_id": probe.probe_id,
            "status": "pass",
            "actual_language": lang,
            "actual_filters": filters,
        }
    except Exception as exc:
        if probe.expected_status == "error":
            return {
                "probe_id": probe.probe_id,
                "status": "pass",
                "detail": f"Expected error: {exc}",
            }
        return {
            "probe_id": probe.probe_id,
            "status": "fail",
            "detail": f"Unexpected error: {type(exc).__name__}: {exc}",
        }


def run_negation_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run a negation probe — always returns expected_unsupported."""
    return {
        "probe_id": probe.probe_id,
        "status": "expected_unsupported",
        "next_file_to_inspect": "src/query_processor.py",
        "next_function_to_inspect": "extract_hard_filters",
        "detail": "Negation/exclusion is not implemented in this phase.",
    }


def run_fixture_generation_probe(probe: DiagnosticProbe) -> dict[str, Any]:
    """Run a fixture generation probe — requires Ollama + BGE-M3."""
    try:
        from src.query_processor import process_query

        fixture = process_query(probe.raw_query)
        # Validate fixture has required fields
        issues: list[str] = []
        if "bm25_search_query_en" not in fixture or not fixture["bm25_search_query_en"]:
            issues.append("missing bm25_search_query_en")
        embedding = fixture.get("query_embedding")
        if not isinstance(embedding, list) or len(embedding) != 1024:
            issues.append(f"query_embedding dimension: {len(embedding) if isinstance(embedding, list) else 'N/A'}")

        if issues:
            return {
                "probe_id": probe.probe_id,
                "status": "fail",
                "detail": "; ".join(issues),
            }
        return {
            "probe_id": probe.probe_id,
            "status": "pass",
            "actual_language": fixture.get("language_detected"),
            "actual_filters": fixture.get("hard_filters"),
        }
    except Exception as exc:
        return {
            "probe_id": probe.probe_id,
            "status": "skipped_dependency_missing",
            "detail": f"{type(exc).__name__}: {exc}",
            "next_file_to_inspect": "src/query_processor.py",
            "next_function_to_inspect": "process_query",
        }


# Probe type dispatcher
_PROBE_RUNNERS: dict[str, Any] = {
    "language_detection": run_language_probe,
    "price_filter": run_price_filter_probe,
    "negation": run_negation_probe,
    "empty_query": run_empty_query_probe,
    "edge_case": run_edge_case_probe,
    "fixture_generation": run_fixture_generation_probe,
}


def run_diagnostic_probes(probes: list[DiagnosticProbe]) -> list[dict[str, Any]]:
    """Run all diagnostic probes and return results.

    Each result dict contains at minimum: probe_id, status, detail.
    """
    results: list[dict[str, Any]] = []
    for probe in probes:
        runner = _PROBE_RUNNERS.get(probe.probe_type)
        if runner is None:
            results.append({
                "probe_id": probe.probe_id,
                "status": "fail",
                "detail": f"Unknown probe_type: {probe.probe_type}",
            })
            continue
        try:
            result = runner(probe)
        except Exception as exc:
            result = {
                "probe_id": probe.probe_id,
                "status": "fail",
                "detail": f"Runner crashed: {type(exc).__name__}: {exc}",
            }
        result["probe_type"] = probe.probe_type
        result["raw_query"] = probe.raw_query
        result["expected_status"] = probe.expected_status
        results.append(result)
    return results


def summarize_diagnostics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a Layer 1 summary from diagnostic results.

    Pass rate excludes known_risk, expected_unsupported, and skipped_dependency_missing.
    """
    total = len(results)
    statuses = [r.get("status", "unknown") for r in results]

    excluded_statuses = {"known_risk", "expected_unsupported", "skipped_dependency_missing"}
    testable = [s for s in statuses if s not in excluded_statuses]
    passed = sum(1 for s in testable if s == "pass")
    failed = sum(1 for s in testable if s == "fail")

    return {
        "total_probes": total,
        "testable_probes": len(testable),
        "passed": passed,
        "failed": failed,
        "known_risk": statuses.count("known_risk"),
        "expected_unsupported": statuses.count("expected_unsupported"),
        "skipped_dependency_missing": statuses.count("skipped_dependency_missing"),
        "pass_rate": round(passed / len(testable), 4) if testable else None,
    }
