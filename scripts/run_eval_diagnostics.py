#!/usr/bin/env python
"""Run Layer 1 diagnostic probes for ColdStart_Killer.

Usage:
    python scripts/run_eval_diagnostics.py \\
        --probes evaluation/queries/diagnostic_probes.json \\
        --out .runtime/evaluation/diagnostics_seed
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.dataset import load_diagnostic_probes
from src.evaluation.diagnostics import run_diagnostic_probes, summarize_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Layer 1 diagnostic probes")
    parser.add_argument("--probes", required=True, help="Path to diagnostic_probes.json")
    parser.add_argument("--out", required=True, help="Output directory")
    args = parser.parse_args()

    probe_path = Path(args.probes)
    if not probe_path.exists():
        print(f"ERROR: Probes file not found: {probe_path}", file=sys.stderr)
        return 1

    probes = load_diagnostic_probes(probe_path)
    print(f"Loaded {len(probes)} diagnostic probes")

    results = run_diagnostic_probes(probes)
    summary = summarize_diagnostics(results)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON output
    with (out_dir / "layer1_diagnostics.json").open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    # CSV output
    if results:
        with (out_dir / "layer1_diagnostics.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()), extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow({k: str(v) if not isinstance(v, (str, int, float, bool)) else v for k, v in r.items()})

    # Summary markdown
    with (out_dir / "layer1_summary.md").open("w", encoding="utf-8") as f:
        f.write("# Layer 1 Diagnostic Summary\n\n")
        f.write(f"**Total probes:** {summary['total_probes']}\n")
        f.write(f"**Testable probes:** {summary['testable_probes']}\n")
        f.write(f"**Passed:** {summary['passed']}\n")
        f.write(f"**Failed:** {summary['failed']}\n")
        f.write(f"**Known risk:** {summary['known_risk']}\n")
        f.write(f"**Expected unsupported:** {summary['expected_unsupported']}\n")
        f.write(f"**Skipped (dependency):** {summary['skipped_dependency_missing']}\n")
        pr = summary['pass_rate']
        f.write(f"**Pass rate:** {pr:.1%}\n" if pr is not None else "**Pass rate:** N/A\n")

    # Manifest
    with (out_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump({
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "artifacts": [
                {"path": "layer1_diagnostics.json", "type": "diagnostics"},
                {"path": "layer1_diagnostics.csv", "type": "diagnostics_csv"},
                {"path": "layer1_summary.md", "type": "summary"},
            ],
        }, f, indent=2)

    print(f"\nPass rate: {summary['pass_rate']:.1%}" if summary['pass_rate'] is not None else "\nPass rate: N/A")
    print(f"Outputs written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
