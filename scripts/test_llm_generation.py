from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm_hype import generate_hype_queries_llm
from src.llm_propositions import extract_propositions_llm


SAMPLE_ITEM = {
    "_id": "sample_local_item",
    "title_en": "Hydrating facial cleanser for sensitive skin",
    "brand": "Demo Brand",
    "raw_main_category": "All Beauty",
    "category_id": "all_beauty",
    "price_bucket": "100k_300k",
    "product_text_for_llm": (
        "Title: Hydrating facial cleanser for sensitive skin\n"
        "Brand: Demo Brand\n"
        "Category: All Beauty\n"
        "Features:\nGentle daily cleanser\nFragrance free\n"
        "Description:\nA mild cleanser for sensitive skin that removes impurities without drying."
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Call Ollama once to test propositions and HyPE generation.")
    parser.parse_args()
    propositions = extract_propositions_llm(SAMPLE_ITEM)
    hype = generate_hype_queries_llm(SAMPLE_ITEM, propositions)
    print(json.dumps({"propositions": propositions, "hype": hype}, indent=2))


if __name__ == "__main__":
    main()

