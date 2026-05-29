#!/usr/bin/env python
"""Run a stable evaluation profile.

Profiles are additive wrappers around scripts/run_evaluation.py. They do not
change artifact contracts or add dashboard writes.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.golden_runs import get_golden_run_profile, list_golden_run_profiles


def build_command(profile_name: str, out_root: str) -> list[str]:
    profile = get_golden_run_profile(profile_name)
    out_dir = Path(out_root) / str(profile["output_subdir"])
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_evaluation.py"),
        "--queries",
        str(profile["queries_path"]),
        "--judgments",
        str(profile["judgments_path"]),
        "--out",
        str(out_dir),
        "--variants",
        *[str(variant) for variant in profile["variants"]],
    ]
    if profile.get("use_fake_results"):
        command.append("--use-fake-results")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a named golden evaluation profile")
    parser.add_argument("--profile", required=True, choices=list_golden_run_profiles())
    parser.add_argument("--out-root", default=".runtime/evaluation/golden")
    parser.add_argument("--print-command", action="store_true", help="Print the underlying command without running it")
    args = parser.parse_args(argv)

    command = build_command(args.profile, args.out_root)
    if args.print_command:
        print(" ".join(part.replace("\\", "/") for part in command))
        return 0

    completed = subprocess.run(command)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
