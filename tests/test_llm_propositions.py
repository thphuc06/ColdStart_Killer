from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm_propositions import _fallback_propositions


def test_fallback_propositions_uses_combined_product_text_sections() -> None:
    item = {
        "_id": "B001",
        "title_en": "Hydrating Facial Cleanser",
        "raw_main_category": "All Beauty",
        "product_text_for_llm": (
            "Title: Hydrating Facial Cleanser\n"
            "Brand: Demo\n"
            "Category: All Beauty\n"
            "Price: 300000 VND\n\n"
            "Features:\nFragrance free\nFor sensitive skin\nRemoves makeup\n\n"
            "Description:\nA gentle daily cleanser that hydrates skin without drying.\n\n"
            "Details:\nSize: 200 ml\nSkin Type: Sensitive"
        ),
    }
    propositions = _fallback_propositions(item)
    texts = [prop["raw_text"] for prop in propositions]
    assert len(propositions) >= 3
    assert "Fragrance free" in texts
    assert any("gentle daily cleanser" in text for text in texts)

