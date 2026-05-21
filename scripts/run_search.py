from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.search_pipeline import run_search


def load_fixture(path: str | Path) -> dict:
    """Load a pre-computed query fixture; no LLM or embedding work happens here."""
    fixture_path = Path(path)
    if not fixture_path.exists():
        raise FileNotFoundError(f"fixture file not found: {fixture_path}")
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"could not read fixture file {fixture_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"fixture file is not valid JSON: {fixture_path}") from exc
    if not isinstance(fixture, dict):
        raise ValueError("fixture JSON must contain an object at the top level")
    return fixture


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MongoDB buyer search from a pre-computed query fixture.")
    parser.add_argument("--fixture", required=True, help="Path to query fixture JSON.")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results to return.")
    parser.add_argument(
        "--mode",
        choices=["auto", "rankFusion", "unionWith"],
        default="unionWith",
        help="Use native $rankFusion, fallback $unionWith, or auto fallback.",
    )
    args = parser.parse_args()

    try:
        fixture = load_fixture(args.fixture)
        results = run_search(fixture, top_k=args.top_k, mode=args.mode)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Search failed: {exc}") from exc
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
