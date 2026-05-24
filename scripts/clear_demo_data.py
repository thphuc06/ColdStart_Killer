from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "QUARANTINED: this old script used to delete catalog data. "
            "Use scripts/reset_demo_behavior_data.py for demo reset/recovery."
        )
    )
    parser.parse_args()
    raise SystemExit(
        "Refusing to run scripts/clear_demo_data.py because it can delete catalog collections. "
        "Use scripts/reset_demo_behavior_data.py --dry-run for behavior-only demo reset."
    )


if __name__ == "__main__":
    main()

