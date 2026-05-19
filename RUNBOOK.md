# ColdStart Killer Runbook

This runbook is the operator guide for the current phase. Follow it when you are ready to run the project on a machine that can download datasets/models, call Ollama, and connect to MongoDB Atlas.

## Current Phase Boundary

This phase does:

- Pull selected Amazon Reviews 2023 product metadata.
- Normalize and audit metadata.
- Build a rich, category-diverse 3,000-item MVP dataset.
- Generate English propositions and English HyPE queries.
- Embed HyPE queries only with BAAI/bge-m3.
- Insert `items` and `retrieval_units` into MongoDB.
- Test one seller product insert through Streamlit.

This phase does not do:

- Buyer search UI.
- Query transformation.
- Hybrid search.
- `$rankFusion`.
- `$unionWith`.
- Evaluation or ablation.

## Phase 0: Setup

Run from the parent folder:

```bash
cd coldstart-killer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```

Create your environment file:

```bash
copy .env.example .env
```

Fill in:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `OLLAMA_MODEL=qwen3:8b`
- `EMBEDDING_MODEL=BAAI/bge-m3`
- `USE_CUDA=true` if your machine has CUDA
- `BRAVE_API_KEY` only if you want seller-side web enrichment

Expected result:

- Virtual environment exists.
- Dependencies install.
- `.env` exists and has MongoDB credentials.

## Phase 1: MongoDB Atlas Manual Setup

Create an Atlas cluster and database manually.

Database:

```text
coldstart_killer
```

Collections:

```text
items
retrieval_units
```

Create the Atlas Vector Search index manually on `retrieval_units`:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    { "type": "filter", "path": "unit_type" },
    { "type": "filter", "path": "aspect" },
    { "type": "filter", "path": "language" },
    { "type": "filter", "path": "category_id" },
    { "type": "filter", "path": "price_bucket" },
    { "type": "filter", "path": "in_stock" },
    { "type": "filter", "path": "is_cold_item" }
  ]
}
```

Create the Atlas Search text index manually on `retrieval_units`:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text_search": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "item_title_en": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "item_brand": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "unit_type": { "type": "string" },
      "proposition_type": { "type": "string" },
      "confidence": { "type": "number" },
      "language": { "type": "string" },
      "category_id": { "type": "string" }
    }
  }
}
```

Then smoke-test connection:

```bash
python scripts/smoke_test_connection.py --counts
```

Expected result:

- `ok: true`
- collection counts are visible, usually `0` before indexing

## Phase 2: Pull, Normalize, Filter, and Build the 3K Dataset

Preferred path: open Notebook 01.

```bash
jupyter lab
```

Run:

```text
notebooks/01_build_3k_mvp_dataset_from_amazon_reviews.ipynb
```

What it does:

- Loads All_Beauty metadata.
- Streams a Cell_Phones_and_Accessories metadata sample.
- Normalizes title, store, category, price, details, features, description, and images.
- Builds `product_text_for_llm`.
- Scores richness.
- Builds a highest-quality control dataset.
- Builds a category-diverse 3,000-item dataset.

Script alternative:

```bash
python scripts/build_3k_mvp_dataset.py
```

Expected output files:

```text
analysis/mvp_3000_items.csv
analysis/mvp_3000_items_diverse.csv
analysis/mvp_3000_selection_report.json
analysis/data_audit_report.md
analysis/data_profile.json
analysis/needs_enrichment_items.csv
```

Expected success checks:

- `analysis/mvp_3000_items_diverse.csv` exists.
- Row count is 3,000 if enough source data is available.
- `parent_asin` is unique.
- `combined_words` is at or above the selected threshold.
- `description_text`, `features_text`, `details_text`, `product_text_for_llm`, `primary_image_url`, and `image_urls` are present.
- Image coverage is reported.

If fewer than 3,000 rows are produced:

- Open `analysis/mvp_3000_selection_report.json`.
- Check selected threshold and warnings.
- Do not fake success; use the best available dataset only if the report explains why.

## Phase 3: Local LLM and Embedding Readiness

Make sure Ollama is installed and the model exists:

```bash
ollama pull qwen3:8b
```

Optional single-call LLM check:

```bash
python scripts/test_llm_generation.py
```

Expected result:

- JSON-like output with `propositions` and `hype`.
- Propositions: 3 to 8.
- HyPE queries: 3 to 6.

Optional embedding check:

```bash
python scripts/test_embeddings.py
```

Expected result:

- `embedding_count: 1`
- `dimension: 1024`
- no NaN/inf/norm validation errors

Note:

- This phase may download BAAI/bge-m3 the first time.
- Use CUDA if available and configured.

## Phase 4: Insert MVP Data into MongoDB

Preferred path: open Notebook 02.

```text
notebooks/02_insert_3k_mvp_to_mongodb.ipynb
```

What it does:

- Loads `analysis/mvp_3000_items_diverse.csv`.
- Validates required columns.
- Estimates vector memory and retrieval-unit counts.
- Dry-runs a few items.
- Shows sample item/proposition/HyPE docs.
- Inserts 10 items.
- Inserts 50 items.
- Leaves 500, 1000, and 3000 inserts as optional cells.

Script dry-run:

```bash
python scripts/index_mvp.py --limit 50 --dry-run
```

Important:

- `--dry-run` still calls Ollama and BAAI/bge-m3.
- `--dry-run` only skips MongoDB writes.

Small write test:

```bash
python scripts/index_mvp.py --limit 10 --write
```

Expected MongoDB document behavior:

- `items` are upserted by `_id`.
- Existing `retrieval_units` for those `item_id`s are deleted.
- New retrieval units are inserted.
- Re-running the same item does not duplicate retrieval units.

Expected counts after 10-item write:

- `items`: at least 10
- `retrieval_units`: roughly 60 to 140, depending on LLM output
- HyPE units have `embedding`
- Proposition units have `text_search` and no `embedding`

## Phase 5: Test Seller Insert UI

Start the UI:

```bash
streamlit run apps/seller_insert_ui.py
```

Manual test path:

1. Confirm MongoDB status panel shows connection OK.
2. Fill seller product fields:
   - `title_en`
   - `brand`
   - `category_id`
   - `category_path`
   - `price_usd` or `price_vnd`
   - `description`
   - `features`, one per line
   - `details JSON`
   - `image_url`
3. Click `Analyze Product`.
4. Check:
   - combined words
   - content richness
   - product text preview
5. Optional: click `Web Enrich`.
6. If enrichment looks useful, check `Accept enrichment`.
7. Click `Generate Retrieval Units`.
8. Check:
   - propositions table has 3 to 8 rows
   - HyPE table has 3 to 6 rows
   - embedding count equals HyPE count
9. Click `Insert to MongoDB`.
10. Confirm success output:
    - `item_id`
    - proposition count
    - HyPE count

Expected behavior:

- Expensive work happens only when buttons are clicked.
- If product input changes after generation, UI warns you to regenerate retrieval units.
- Re-inserting the same seller product replaces old retrieval units.
- If `BRAVE_API_KEY` is missing, enrichment is skipped gracefully and insertion can continue.

## Phase 6: Optional Cleanup

To clear demo data:

```bash
python scripts/clear_demo_data.py --yes --seller-only
```

To clear Amazon MVP plus seller demo data:

```bash
python scripts/clear_demo_data.py --yes
```

Use cleanup carefully. It deletes documents from MongoDB.

## Troubleshooting

MongoDB connection fails:

- Check `MONGODB_URI`.
- Check Atlas IP allowlist.
- Check username/password.
- Check cluster is running.

Dataset loading fails:

- Check network access.
- Check Hugging Face dataset URLs.
- Open `analysis/mvp_3000_selection_report.json` if partial output exists.

Ollama generation fails:

- Run `ollama list`.
- Pull `qwen3:8b`.
- Confirm Ollama server is running.

Embedding fails:

- First run may download BAAI/bge-m3.
- If CUDA is not available, set `USE_CUDA=false`.
- Dimension must be 1024.

Streamlit reruns often:

- This is normal.
- MongoDB status is cached briefly.
- LLM, embeddings, enrichment, and inserts only happen on explicit button clicks.

