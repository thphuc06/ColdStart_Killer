from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.enrichment import agentic_web_enrich


SAMPLE_ITEM = {
    "title_en": "Hydrating facial cleanser for sensitive skin",
    "brand": "Demo Brand",
    "raw_main_category": "All Beauty",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Test seller-only Brave enrichment.")
    parser.parse_args()
    print(json.dumps(agentic_web_enrich(SAMPLE_ITEM), indent=2))


if __name__ == "__main__":
    main()

