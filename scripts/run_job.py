from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.jobs.registry import get_job_registry_payload
from src.jobs.runner import JobRejectedError, run_registered_job, sanitize_job_params


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or preview registered ColdStart Killer jobs.")
    parser.add_argument("--list", action="store_true", help="List registered jobs and exit.")
    parser.add_argument("--job", help="Job type to run.")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Run in dry-run mode. This is the default.")
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry-run mode. Write-capable jobs still require --write and --confirm.",
    )
    parser.add_argument("--write", action="store_true", help="Request a write-capable job. Requires confirmation.")
    parser.add_argument("--confirm", default=None, help="Confirmation string for write-capable jobs.")
    parser.add_argument("--track", action="store_true", help="Persist compact job_runs status to MongoDB.")
    parser.add_argument("--no-track", action="store_true", help="Do not write job_runs tracking. This is the default.")
    parser.add_argument("--param", action="append", default=[], help="Optional key=value parameter. Repeatable.")
    return parser.parse_args(argv)


def _parse_params(values: list[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            params[value] = True
            continue
        key, raw = value.split("=", 1)
        params[key] = raw
    return params


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print(json.dumps({"ok": True, "jobs": get_job_registry_payload()}, indent=2))
        return 0
    if not args.job:
        print("ERROR: pass --list or --job <job_type>.", file=sys.stderr)
        return 2
    if args.track and args.no_track:
        print("ERROR: choose either --track or --no-track.", file=sys.stderr)
        return 2
    settings = get_settings()
    collection = None
    track = bool(args.track)
    if track:
        from src.mongodb import get_job_runs_collection

        collection = get_job_runs_collection()
    try:
        run = run_registered_job(
            args.job,
            params=_parse_params(args.param),
            dry_run=bool(args.dry_run),
            write=args.write,
            confirm=args.confirm,
            collection=collection,
            created_by="cli",
            track=track,
            allow_non_triggerable=True,
            api_trigger=False,
            global_confirmation=settings.job_run_confirmation,
        )
    except JobRejectedError as exc:
        print(json.dumps({"ok": False, "error": "job_rejected", "message": str(exc)}, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": "job_failed", "message": sanitize_job_params(str(exc))}, indent=2),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, "tracked": track, "run": sanitize_job_params(run)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
