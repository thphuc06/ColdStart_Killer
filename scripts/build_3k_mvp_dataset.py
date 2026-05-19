from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mvp_selection import build_3k_mvp_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the 3,000-item MVP dataset.")
    parser.parse_args()
    result = build_3k_mvp_dataset()
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

