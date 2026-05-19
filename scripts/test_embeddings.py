from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embeddings import embed_texts, estimate_vector_memory


def main() -> None:
    parser = argparse.ArgumentParser(description="Download/load BAAI/bge-m3 and encode sample text.")
    parser.add_argument("--text", default="gentle cleanser for sensitive skin", help="Text to embed.")
    args = parser.parse_args()
    vectors = embed_texts([args.text])
    result = {
        "embedding_count": len(vectors),
        "dimension": len(vectors[0]) if vectors else 0,
        "memory_estimate": estimate_vector_memory(len(vectors)),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

