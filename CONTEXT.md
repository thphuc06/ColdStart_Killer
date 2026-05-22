# ColdStart Killer Context

## Project Summary

ColdStart Killer is an ecommerce cold-start retrieval project for MongoDB Atlas. A product is the business entity. Retrieval units are semantic entry points that make new products searchable before user interaction history exists.

## Current Phase Scope

This phase builds:

- A notebook-generated 3,000-item MVP dataset from Amazon Reviews 2023 metadata.
- MongoDB insertion code for `items` and `retrieval_units`.
- Buyer query processing and hybrid retrieval checks through notebooks/scripts.
- **Retrieval evaluation** framework with 3 layers (diagnostics, IR metrics, demo readiness), 5 search variants, 50 queries, 20 probes.

This phase explicitly does not build:

- Buyer search UI.

## Dataset Policy

Source dataset: McAuley-Lab Amazon Reviews 2023 on Hugging Face.

Target sources:

- All_Beauty metadata, full parquet if available, streaming JSONL fallback.
- Cell_Phones_and_Accessories metadata, streaming JSONL first 20,000 rows.
- Optional All_Beauty review sample, audit metadata only.

Reviews are not retrieval features in this phase.

## MVP 3K Filter Policy

The primary dataset is `analysis/mvp_3000_items_diverse.csv`.

Rules:

- Target 3,000 rows and 3,000 unique `parent_asin` when enough data exists.
- Deduplicate by `parent_asin`, keeping the richest text row.
- Require title, store, category, non-zero price, useful product text, and either description or features.
- Start with `combined_words >= 150`.
- If needed, retry thresholds 120, 100, then 80.
- Prefer products with images and report image coverage.
- Cap dominant categories at 1,200 items.

## MongoDB Schema

Collections:

- `items`: one document per product.
- `retrieval_units`: semantic units for later retrieval.

`items._id` is the product id, usually `parent_asin` for Amazon data.

`retrieval_units` includes:

- HyPE units with dense embeddings.
- Proposition units with text-search fields only.

## HyPE and Proposition Rules

Language:

- English only.
- No Vietnamese segmentation.
- No bilingual HyPE.

HyPE:

- 3 to 6 queries per item.
- Required aspects: function, persona, occasion.
- Optional aspects: constraint, compatibility, style, gift, spec, problem.
- Embedded with BAAI/bge-m3.
- Embedding dimension: 1024.

Propositions:

- 3 to 8 facts per item.
- Confidence threshold: >= 0.60.
- Grounded only in product metadata.
- Not embedded.
- Stored in `text_search` for later BM25/Atlas Search.

## Image Handling

Image URLs are preserved from Amazon metadata into:

- `primary_image_url`
- `image_urls`
- `items.image_url`
- `items.image_urls`

The MVP selection prefers image-backed rows but does not hard-fail otherwise excellent products when source image coverage is insufficient.

## Manual MongoDB Atlas Setup

Create indexes manually. The code does not create Atlas indexes.

Vector Search:

- Collection: `retrieval_units`
- Vector field: `embedding`
- Dimensions: 1024
- Similarity: cosine
- Filter fields: `unit_type`, `aspect`, `language`, `category_id`, `price_bucket`, `in_stock`, `is_cold_item`

Atlas Search:

- Collection: `retrieval_units`
- Text field: `text_search`
- Analyzer: `lucene.standard`
- Also map: `embedding_text`, `raw_text`, `item_title_en`, `item_brand`, `unit_type`, `proposition_type`, `confidence`, `language`, `category_id`, `in_stock`, `is_cold_item`, `aspect`

## Known Limitations

- Embeddings are stored as normal Python float lists for MVP simplicity.
- `bindata_float32` is not implemented yet.
- Bulk LLM generation is sequential and intentionally conservative.

## LLM Configuration

- **Model**: Qwen3:8b running locally via Ollama.
- **Uses**: Vietnamese→English translation (`query_processor.py`), HyPE query generation (`llm_hype.py`), proposition extraction (`llm_propositions.py`).
- **Config**: Set `OLLAMA_MODEL=qwen3:8b` in `.env`. Default in `src/config.py`.

## Evaluation Framework

The evaluation framework measures retrieval quality across 5 search variants:

- `title_only` — weak regex baseline on `items.title_en`.
- `vector_only` — HyPE vector search only.
- `bm25_only` — BM25 proposition search only.
- `hybrid_union` — production pipeline (vector + BM25 + bonuses).
- `hybrid_no_cold_boost` — ablation: remove `COLD_START_BOOST`.

Key files:

- `src/evaluation/` — Python package (contracts, dataset, diagnostics, metrics, variants, runner, reporting).
- `evaluation/` — Data files (50 queries, 20 probes, judgments).
- `scripts/run_evaluation.py` — CLI (supports `--use-fake-results` for smoke testing without MongoDB).
- `notebooks/05_evaluation_retrieval_quality.ipynb` — Interactive evaluation notebook.

## Commands to run later

For detailed run phases, expected outputs, UI checks, and troubleshooting, use `RUNBOOK.md`.

```bash
cd coldstart-killer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python scripts/smoke_test_connection.py

jupyter lab

python scripts/build_3k_mvp_dataset.py
python scripts/index_mvp.py --limit 50 --dry-run
python scripts/index_mvp.py --limit 10 --write
python scripts/index_mvp.py --limit 500 --write --resume
python scripts/test_llm_generation.py
python scripts/test_embeddings.py
python scripts/run_search.py --help
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```

## Next Phase Suggestion

Build buyer-facing UI polish after evaluation results are reviewed:

- Buyer-facing UI polish if needed.
- Expand judgment labeling for more complete NDCG/Recall scores.
- Add more evaluation queries for underrepresented slices.
