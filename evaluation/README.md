# Evaluation Framework

This directory contains the evaluation dataset for ColdStart_Killer retrieval quality assessment.

## Structure

```
evaluation/
  queries/
    diagnostic_probes.json     — 20 Layer-1 diagnostic probes
    retrieval_queries_seed.json — 50 Layer-2 retrieval queries
  judgments/
    retrieval_judgments_seed.json — relevance judgments (initially empty)
```

## Labeling Rules

### Relevance Scale

| Score | Label | Meaning |
|---|---|---|
| 3 | Highly Relevant | Perfect or near-perfect match. Directly answers the query intent. |
| 2 | Relevant | Useful result. Addresses the query but may lack specificity. |
| 1 | Marginally Relevant | Tangentially related. Same category but doesn't address the specific need. |
| 0 | Not Relevant | No connection to the query intent. Wrong category or clearly irrelevant. |

### Labeling Decision Tree

1. **Does the product exist and have a valid title?** → No → Score 0
2. **Is the product in the correct category for the query?** → No → Score 0
3. **Does the product match the core intent?** → No → Score 1 (category match only)
4. **Does the product satisfy stated constraints (skin type, price, brand)?** → No → Score 2 (intent match, constraint miss)
5. **Would you recommend this result to the user?** → Yes → Score 3, No → Score 2

### Price Filter Rules

- If the query specifies a price constraint and the result violates it, cap relevance at 1.
- The price filter compliance is checked through `expected_filters` in the query definition.

### Cold-Start Labels

Use the `labels` field to annotate cold-start items:
- `cold_item` — item is a cold-start item with limited interaction history
- `new_seller` — item from a new/unverified seller

### Estimated Labeling Time

- ~2-3 minutes per (query, item) pair
- ~50 queries × ~5 unique items per query = ~250 pairs
- Total: ~8-12 hours for first pass

## Metric Definitions

| Metric | Definition |
|---|---|
| NDCG@K | Normalized Discounted Cumulative Gain at rank K |
| Precision@K | Fraction of top-K results that are relevant |
| Recall@K | Fraction of all relevant items found in top-K |
| MRR@K | Reciprocal rank of the first relevant result |
| HitRate@K | 1 if any relevant result in top-K, else 0 |
| ColdRelevantRate@K | Fraction of cold items in top-K that are relevant |
| ColdShareOfRelevant@K | Fraction of relevant results that are cold items |
| RawColdCoverage@K | Fraction of top-K that are cold items (diagnostic only) |

## Running Evaluation & Judgment Workflow

To measure search metrics (like NDCG, Recall, MRR), the system requires human relevance judgments. Follow this 4-step workflow to generate and run evaluation:

### Step 1: Run Layer-1 Diagnostics (No MongoDB required)
Verify query parsing, extraction, and language detection capabilities:
```bash
python scripts/run_eval_diagnostics.py \
    --probes evaluation/queries/diagnostic_probes.json \
    --out .runtime/evaluation/diagnostics_seed
```

### Step 2: Build the Judgment Pool (Requires MongoDB)
Run the seed queries against all 5 system variants to collect candidates for human evaluation:
```bash
python scripts/build_eval_pool.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --out .runtime/evaluation/pool_seed \
    --top-k 20
```
This generates `.runtime/evaluation/pool_seed/judgment_pool.csv` containing unique `(query_id, item_id)` pairs.

### Step 3: Manual Labeling
Open the generated `judgment_pool.csv` in Excel, Google Sheets, or any CSV editor:
1. **Relevance Column**: Fill in integer scores from `0` to `3` based on the [Labeling Rules](#labeling-rules).
2. **Reason Column** (Optional): Add notes/explanations for your score.
3. **Labels Column** (Optional): Add comma-separated tags (e.g. `cold_item`, `new_seller`) if applicable.

### Step 4: Import Judgments to JSON
Once labeled, run the import script to convert the CSV file back into the validated evaluation contract JSON:
```bash
python scripts/import_eval_judgments.py \
    --csv .runtime/evaluation/pool_seed/judgment_pool.csv \
    --out evaluation/judgments/retrieval_judgments_seed.json
```
*Note: Add the `--strict` flag to fail if there are any invalid/empty relevance values.*

### Step 5: Run Full Evaluation (Requires Judgments)
Now that `evaluation/judgments/retrieval_judgments_seed.json` is populated, run the full evaluation:
```bash
python scripts/run_evaluation.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --judgments evaluation/judgments/retrieval_judgments_seed.json \
    --out .runtime/evaluation/eval_seed
```

### Smoke Test (No external dependencies)
You can test the reporting pipeline with synthetic search results and judgments:
```bash
python scripts/run_evaluation.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --judgments evaluation/judgments/retrieval_judgments_seed.json \
    --out .runtime/evaluation/smoke \
    --use-fake-results
```

