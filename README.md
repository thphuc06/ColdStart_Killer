# ColdStart Killer

ColdStart Killer is a MongoDB Hackathon project for bootstrapping retrieval for brand-new ecommerce products. The current phase builds a high-quality 3,000-item MVP dataset from Amazon Reviews 2023 metadata, inserts item and retrieval-unit documents into MongoDB, and provides a seller-side Streamlit insert simulation.

## Current Phase Scope

This phase includes:

- Notebook dataset building from selected Amazon Reviews 2023 metadata.
- Notebook-driven MongoDB insertion.
- Seller product insertion UI.
- English propositions and English HyPE queries.
- BAAI/bge-m3 embeddings for HyPE queries only.
- Product images preserved for UI display.

This phase does not include:

- Full buyer query pipeline.
- Hybrid search.
- `$rankFusion`.
- `$unionWith`.
- Full evaluation or ablation.
- Buyer search UI beyond status/count panels.

## Notebook-First Demo Philosophy

The notebooks are the technical proof:

- `notebooks/01_build_3k_mvp_dataset_from_amazon_reviews.ipynb` audits and builds the MVP dataset.
- `notebooks/02_insert_3k_mvp_to_mongodb.ipynb` estimates and inserts documents into MongoDB in controlled increments.

The Streamlit app is the product simulation:

- `apps/seller_insert_ui.py` lets a seller enter one new product, optionally enrich it with Brave Search, generate retrieval units, embed HyPE queries, and insert the result into MongoDB.

## Verified Implementation Notes

Implementation details were checked against official documentation:

- Hugging Face Datasets streaming/loading: https://huggingface.co/docs/datasets/dataset_streaming
- Amazon Reviews 2023 dataset card: https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023
- MongoDB Atlas Vector Search index fields: https://www.mongodb.com/docs/atlas/atlas-vector-search/create-index/
- MongoDB Atlas Search field mappings and standard analyzer: https://www.mongodb.com/docs/atlas/atlas-search/define-field-mappings/
- PyMongo bulk writes and `UpdateOne(..., upsert=True)`: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/write/bulk-write/
- Ollama chat `think` parameter: https://docs.ollama.com/api/chat
- Streamlit `st.session_state`: https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
- SentenceTransformers `encode(..., normalize_embeddings=True)`: https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html
- BAAI/bge-m3 model card: https://huggingface.co/BAAI/bge-m3

## Setup

Use a virtual environment, install dependencies, then copy `.env.example` to `.env` and fill in the values.

Required environment variables:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `OLLAMA_MODEL`
- `BRAVE_API_KEY` for optional seller-side web enrichment
- `EMBEDDING_MODEL`
- `USE_CUDA`
- `EMBEDDING_STORAGE_FORMAT`

Default embedding storage is `list_float` for simplicity in this MVP. The code is organized so a later `bindata_float32` option can be added without changing the retrieval-unit schema contract.

## MongoDB Atlas Manual Steps

Create the Atlas cluster and database manually. This code does not create Atlas indexes automatically.

Collections:

- `items`
- `retrieval_units`

### Vector Search Index

Create this Atlas Vector Search index manually on `retrieval_units`.

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

### Atlas Search Text Index

Create this Atlas Search index manually on `retrieval_units`.

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

## Run Order

1. Build the MVP dataset in Notebook 01.
2. Create the MongoDB Atlas Vector Search and Atlas Search indexes manually.
3. Insert items and retrieval units in Notebook 02.
4. Run the Streamlit seller insert UI.

For the full operator walkthrough, use [`RUNBOOK.md`](RUNBOOK.md).

## Data Policy

Dataset loading uses selected Amazon Reviews 2023 metadata only:

- All_Beauty metadata: full parquet first, streaming JSONL fallback.
- Cell_Phones_and_Accessories metadata: streaming JSONL, first 20,000 rows.
- Optional All_Beauty review sample: audit metadata only.

Reviews are not used as retrieval features.

## MVP Selection Policy

The primary insert/test dataset is `analysis/mvp_3000_items_diverse.csv`.

Required filters:

- `parent_asin`, title, store, category, price, and product text present.
- Price parsed and non-zero.
- Description or features present.
- Combined text words >= 150 when enough data is available.
- Unique `parent_asin`.

Fallback thresholds are 120, 100, then 80 if 3,000 useful items cannot be reached at 150. Image rows are preferred, with a 95% coverage target when the source data makes it possible.

## Retrieval Units

HyPE units:

- `unit_type = "hype_question"`
- English only.
- Dynamic 3 to 6 per item.
- Required aspects: function, persona, occasion.
- Embedded with BAAI/bge-m3.
- Stored in `retrieval_units.embedding`.

Proposition units:

- `unit_type = "proposition"`
- English only.
- Dynamic 3 to 8 per item.
- Confidence >= 0.60.
- Stored in `retrieval_units.text_search`.
- Not embedded.

## Limits

- Default indexing limit: 50.
- Dev limit: 500.
- M0 safe limit: 3000.
- Dedicated full limit: 5000.

Bulk MVP indexing is sequential for Ollama calls and defaults to MongoDB dry-run behavior in the script unless `--write` is passed. `--dry-run` still calls Ollama and BAAI/bge-m3 to prepare documents; it only skips MongoDB writes.

## Commands to run later

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
python scripts/test_llm_generation.py
python scripts/test_embeddings.py
python scripts/test_web_enrichment.py

streamlit run apps/seller_insert_ui.py
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```
