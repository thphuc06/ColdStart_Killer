from __future__ import annotations

import logging
from typing import Any

from datasets import load_dataset
from tqdm.auto import tqdm

from .normalize_amazon import USD_TO_VND


logger = logging.getLogger(__name__)

SEED = 42
CELL_SAMPLE_N = 20_000
REVIEW_SAMPLE_N = 50_000
MVP_TARGET_N = 3_000
MIN_COMBINED_WORDS = 150
MAX_PER_CATEGORY = 1_200

REPO_BASE_URL = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main"

URLS = {
    "All_Beauty_parquet": f"{REPO_BASE_URL}/raw_meta_All_Beauty/full-00000-of-00001.parquet",
    "All_Beauty_jsonl": f"{REPO_BASE_URL}/raw/meta_categories/meta_All_Beauty.jsonl",
    "Cell_Phones_jsonl": f"{REPO_BASE_URL}/raw/meta_categories/meta_Cell_Phones_and_Accessories.jsonl",
    "All_Beauty_reviews_jsonl": f"{REPO_BASE_URL}/raw/review_categories/All_Beauty.jsonl",
}


def _failure(failures: list[dict[str, str]], source: str, exc: Exception) -> None:
    message = f"{type(exc).__name__}: {exc}"
    logger.warning("Dataset load failed for %s: %s", source, message)
    failures.append({"source": source, "error": message})


def records_from_dataset(dataset: Any, limit: int | None, desc: str) -> list[dict]:
    records: list[dict] = []
    iterator = iter(dataset)
    progress = tqdm(iterator, total=limit, desc=desc)
    for idx, row in enumerate(progress):
        if limit is not None and idx >= limit:
            break
        records.append(dict(row))
    return records


def load_all_beauty_metadata(failures: list[dict[str, str]]) -> tuple[list[dict], str]:
    try:
        dataset = load_dataset("parquet", data_files=URLS["All_Beauty_parquet"], split="train")
        return records_from_dataset(dataset, limit=None, desc="All_Beauty parquet"), "All_Beauty_parquet"
    except Exception as exc:
        _failure(failures, "All_Beauty_parquet", exc)

    try:
        dataset = load_dataset("json", data_files=URLS["All_Beauty_jsonl"], split="train", streaming=True)
        return records_from_dataset(dataset, limit=None, desc="All_Beauty jsonl stream"), "All_Beauty_jsonl"
    except Exception as exc:
        _failure(failures, "All_Beauty_jsonl", exc)
        return [], "All_Beauty_failed"


def load_cell_metadata(
    failures: list[dict[str, str]], sample_n: int = CELL_SAMPLE_N
) -> tuple[list[dict], str]:
    try:
        dataset = load_dataset("json", data_files=URLS["Cell_Phones_jsonl"], split="train", streaming=True)
        return records_from_dataset(dataset, limit=sample_n, desc="Cell_Phones stream sample"), "Cell_Phones_jsonl"
    except Exception as exc:
        _failure(failures, "Cell_Phones_jsonl", exc)
        return [], "Cell_Phones_failed"


def load_review_sample(failures: list[dict[str, str]], sample_n: int = REVIEW_SAMPLE_N) -> list[dict]:
    try:
        dataset = load_dataset(
            "json", data_files=URLS["All_Beauty_reviews_jsonl"], split="train", streaming=True
        )
        return records_from_dataset(dataset, limit=sample_n, desc="All_Beauty review sample")
    except Exception as exc:
        _failure(failures, "All_Beauty_reviews_jsonl", exc)
        return []


def load_target_metadata() -> tuple[list[dict], dict]:
    failures: list[dict[str, str]] = []
    all_beauty, all_beauty_source = load_all_beauty_metadata(failures)
    cell, cell_source = load_cell_metadata(failures, CELL_SAMPLE_N)

    tagged_records = []
    for record in all_beauty:
        row = dict(record)
        row["_source_category"] = "All_Beauty"
        tagged_records.append(row)
    for record in cell:
        row = dict(record)
        row["_source_category"] = "Cell_Phones_and_Accessories"
        tagged_records.append(row)

    report = {
        "sources": {
            "all_beauty": all_beauty_source,
            "cell_phones": cell_source,
        },
        "row_counts": {
            "all_beauty": len(all_beauty),
            "cell_phones": len(cell),
            "combined": len(tagged_records),
        },
        "failures": failures,
        "policy": {
            "cell_sample_n": CELL_SAMPLE_N,
            "review_sample_optional": True,
            "reviews_used_for_retrieval_features": False,
        },
    }
    return tagged_records, report

