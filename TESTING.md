# 🧪 ColdStart Killer — Testing Guide

Tài liệu này là testing guide chính thức cho ColdStart Killer. Nội dung bao gồm setup, unit tests, integration notebooks, demo end-to-end, CLI search, và checklist trước khi demo.

Người nên đọc: teammate phụ trách indexing/seller flow, người phụ trách buyer search pipeline, và bất kỳ ai cần verify hệ thống trước khi push GitHub hoặc record demo.

---

## 📋 Yêu cầu trước khi test

| Yêu cầu | Máy Teammate | Máy Search |
|---------|-------------|------------|
| MongoDB URI (.env) | ✅ | ✅ |
| Ollama + Qwen3:8b | ✅ | ❌ |
| BAAI/bge-m3 model | ✅ | ❌ |
| Python 3.10+ | ✅ | ✅ |
| pip install -r requirements.txt | ✅ | ⚠️ chỉ cần pymongo pydantic python-dotenv pytest numpy |

---

## ⚙️ Setup

### Bước 1 — Clone và cài dependencies

Full install cho máy teammate:

```bash
git clone <repo-url>
cd ColdStart_Killer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Minimal install cho máy search:

```bash
git clone <repo-url>
cd ColdStart_Killer
python -m venv .venv
.venv\Scripts\activate
pip install pymongo pydantic python-dotenv pytest numpy
```

### Bước 2 — Tạo file .env

Tạo file `.env` ở repo root:

```bash
# ── Shared (cả 2 máy cần) ──────────────────────
MONGODB_URI="mongodb+srv://<username>:<password>@<cluster>/?retryWrites=true&w=majority"
MONGODB_DB_NAME="coldstart_killer"
MONGODB_TIMEOUT_MS=10000

# ── Teammate machine only (máy search không cần) ──
OLLAMA_MODEL="qwen3:8b"
EMBEDDING_MODEL="BAAI/bge-m3"
USE_CUDA=true
EMBEDDING_STORAGE_FORMAT="list_float"
DEFAULT_INDEX_LIMIT=50
M0_SAFE_LIMIT=3000
DEDICATED_FULL_LIMIT=5000
```

⚠️ KHÔNG commit `.env` lên GitHub.

### Bước 3 — Verify kết nối MongoDB

```bash
python scripts/smoke_test_connection.py --counts
```

Expected output ví dụ:

```json
{
  "ok": true,
  "result": {"ok": 1},
  "database": "coldstart_killer",
  "counts": {
    "ok": true,
    "items": 3000,
    "retrieval_units": 29753
  }
}
```

Live MongoDB snapshot đã verify:

| Metric | Value |
|--------|------:|
| items | 3,000 |
| retrieval_units | 29,753 |
| HyPE units | 13,580 |
| proposition units | 16,173 |
| cold items | 3,000 (100% cold — interaction_count=0) |
| categories | All_Beauty, Cell_Phones_and_Accessories |
| VECTOR_NUM_CANDIDATES | 400 |
| VECTOR_CHANNEL_LIMIT | 20 |

Atlas Search `text_index` phải có mapping đầy đủ sau:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text_search":    { "analyzer": "lucene.standard", "type": "string" },
      "embedding_text": { "analyzer": "lucene.standard", "type": "string" },
      "raw_text":       { "analyzer": "lucene.standard", "type": "string" },
      "item_title_en":  { "analyzer": "lucene.standard", "type": "string" },
      "item_brand":     { "analyzer": "lucene.standard", "type": "string" },
      "unit_type":      { "type": "string" },
      "language":       { "type": "string" },
      "in_stock":       { "type": "boolean" },
      "is_cold_item":   { "type": "boolean" },
      "category_id":    { "type": "string" },
      "confidence":     { "type": "number" },
      "proposition_type": { "type": "string" }
    }
  }
}
```

⚠️ Quan trọng: `text_index` phải có đủ tất cả các fields trên để BM25 search hoạt động đúng.

### Bước 4 — Verify frontend Phase 11

Frontend demo dùng React + Vite + TypeScript và mặc định gọi API tại `http://127.0.0.1:8000`.

Build check:

```bash
cd frontend
npm install
npm run test:ui
npm run build
```

`npm run test:ui` chạy route-level UI checks cho homepage, search, item detail, và debug bằng jsdom + mocked API contract. Đây là gate ổn định nhất để verify Phase 11 frontend logic trước khi chạy browser/demo thật.

Local dev check:

```bash
uvicorn src.api.app:app --reload

# terminal khác
cd frontend
npm run dev
```

Live Phase 11 smoke check:

```bash
uvicorn src.api.app:app --host 127.0.0.1 --port 8000

# terminal khác
cd frontend
npm run smoke:e2e
```

`npm run smoke:e2e` verify live contract cho homepage feed, search, item detail, similar products, event logging, và debug user flow. Kết quả được ghi vào `.runtime/phase11_smoke/result.json`.

Nếu API chạy ở host/port khác, copy `frontend/.env.example` thành `frontend/.env` và đổi `VITE_API_BASE_URL`.

---

## 🔬 Test 1 — Unit Tests (không cần MongoDB)

Unit tests có thể chạy trên cả 2 máy. Phần lớn tests không cần live services, nhưng một số test liên quan indexing/LLM cần Ollama hoặc embedding dependencies.

```bash
python -m pytest tests/ -v
```

Expected output:

```bash
============================= test session starts =============================
tests/... PASSED
============================== all tests passed ==============================
```

| Test file | Nội dung kiểm tra | Cần Ollama/embedding? |
|-----------|-------------------|------------------------|
| tests/test_pipeline.py | buyer search pipeline structure | ❌ |
| tests/test_validation.py | data validation | ❌ |
| tests/test_normalize_amazon.py | normalization | ❌ |
| tests/test_mvp_selection.py | dataset selection | ❌ |
| tests/test_evaluation_dataset.py | evaluation contracts + data loading | ❌ |
| tests/test_evaluation_metrics.py | IR metrics (NDCG, MRR, etc.) | ❌ |
| tests/test_evaluation_diagnostics.py | diagnostic probe runners | ❌ |
| tests/test_evaluation_guardrails.py | import safety, read-only, constant mutation | ❌ |
| tests/test_evaluation_runner.py | evaluation runner + reporting | ❌ |
| tests/test_evaluation_variants.py | variant runners + failure handling | ❌ |
| tests/test_import_eval_judgments.py | AI-assisted judgment import script | ❌ |
| tests/test_indexing.py | indexing | ✅ requires Ollama |
| tests/test_llm_propositions.py | LLM propositions | ✅ requires Ollama |
| tests/test_llm_client.py | LLM client | ✅ requires ollama package |

---

## 🏥 Test 2 — Integration Health Test (Notebook 03)

> ⚠️ Yêu cầu: Chạy trên máy teammate  
> Notebook này gọi `process_query()` để tạo query embedding
> bằng BAAI/bge-m3. Máy search (RAM thấp, không có model)
> không thể chạy notebook này.

Notebook này verify full pipeline có healthy không trên live MongoDB. Test này cần máy teammate vì `query_processor` cần BAAI/bge-m3 để tạo `query_embedding`.

### Cách chạy

1. Mở VSCode
2. Mở `notebooks/03_buyer_search_pipeline_test.ipynb`
3. Chọn Python kernel
4. Run All Cells

### Kết quả mong đợi

```bash
- Collection health: PASS
- Pipeline returns results: PASS
- Hybrid channels working: PASS
- Field contract: PASS
- Ready for Demo: YES
```

### Troubleshooting

| Lỗi | Nguyên nhân | Cách fix |
|-----|------------|---------|
| MongoDB connection failed | Sai URI hoặc IP chưa whitelist | Kiểm tra .env và Atlas Network Access |
| ModuleNotFoundError: sentence_transformers | Chưa install | pip install sentence-transformers torch |
| Ollama connection refused | Ollama chưa chạy | Chạy: ollama serve |
| Collection health: FAIL | Chưa index data | Chạy scripts/index_mvp.py --write |
| Hybrid channels: FAIL | Atlas index chưa READY | Đợi Atlas index rebuild xong |

---

## 🎬 Test 3 — Demo End-to-End (Notebook 04)

> ⚠️ Yêu cầu: Chạy trên máy teammate  
> Notebook này cần BAAI/bge-m3 (embedding) và
> Qwen3:8b via Ollama (Vietnamese translation).

Notebook này chạy full demo từ user query thật → kết quả. Test này cần máy teammate vì có translation bằng Qwen3 và embedding bằng BAAI/bge-m3.

### Cách chạy

1. Mở `notebooks/04_demo_buyer_search.ipynb`
2. Vào Cell 3 — đổi QUERY:

```python
QUERY = "tai nghe không dây dưới 500k"  # ← đổi query ở đây
TOP_K = 10
```

3. Run All Cells

### Query examples để test

| Query | Ngôn ngữ | Filter | Mục đích test |
|-------|----------|--------|---------------|
| "tai nghe không dây dưới 500k" | Tiếng Việt | price_max: 500000 | Vietnamese + price filter, electronics |
| "moisturizing cream for dry skin" | English | none | English beauty query |
| "phone case samsung galaxy s22" | English | none | Cell phone accessory |
| "sạc nhanh usb c iphone" | Tiếng Việt | none | Vietnamese electronics |
| "wireless charger under 300k" | English | price_max: 300000 | English + price filter |

### Kết quả mong đợi cho từng section

- Section Query Processing: hiển thị language detected, english translation, filters extracted, embedding 1024-dim
- Section Hybrid Search: hiển thị mode `unionWith`, N results returned
- Section Results: ranked table có score, matched_intent, matched_fact
- Section Cold Start: hiển thị items được surface dù zero interactions
- Section Debug: hiển thị fusion scores và channel contributions
- Section Summary: tất cả checks là YES

### Troubleshooting

| Lỗi | Nguyên nhân | Cách fix |
|-----|------------|---------|
| ValueError: raw_query must be non-empty | Query rỗng | Điền query vào Cell 3 |
| Ollama connection refused | Ollama chưa chạy | ollama serve |
| Empty results [] | Atlas index chưa ready hoặc data chưa index | Kiểm tra Atlas index status |
| Translation không hoạt động | Ollama/Qwen chưa pull | ollama pull qwen3:8b |
| BGE-M3 download chậm | Lần đầu chạy ~1.5GB | Chờ download xong |

---

## 📊 Test 4 — CLI Search (Không cần embedding)

CLI search là quick search test không cần chạy full notebook. Có thể chạy trên máy search nếu đã có fixture được tạo sẵn.

```bash
python scripts/run_search.py --fixture <fixture.json> --top-k 10 --mode unionWith
```

Fixture format:

```json
{
  "original_query": "tai nghe chống ồn dưới 500k",
  "hype_search_query_en": "user looking for noise cancelling headphones under 500k vnd for everyday use",
  "bm25_search_query_en": "noise cancelling headphones 500k",
  "hard_filters": {
    "in_stock": true,
    "price_max": 500000
  },
  "query_embedding": [-0.018, -0.006, "... 1024 floats total"]
}
```

Note:

- `category_id` is NOT a hard filter — category intent is handled by BGE-M3 embedding semantics in `$vectorSearch`. `hard_filters` only supports: `in_stock`, `price_max`, `price_min`.
- `query_embedding` là float array 1024-dim được tạo bởi BAAI/bge-m3.

---

## ✅ Checklist trước khi Demo

- [ ] MongoDB connected (smoke_test_connection PASS)
- [ ] Data indexed (~3,000 items, ~29,753 retrieval_units)
- [ ] HyPE units indexed (~13,580 HyPE units)
- [ ] Proposition units indexed (~16,173 proposition units)
- [ ] Atlas vector_index status: READY
- [ ] Atlas text_index status: READY
- [ ] Ollama running (ollama serve)
- [ ] Qwen3:8b pulled (ollama pull qwen3:8b)
- [ ] BGE-M3 downloaded
- [ ] Notebook 03 all PASS
- [ ] Notebook 04 runs end-to-end with sample query
- [ ] Notebook 05 evaluation runs (at least smoke test mode)
- [ ] `python -m pytest tests/test_evaluation_*.py -v` all pass

---

## 🗂️ Cấu trúc repo liên quan đến testing

```bash
tests/                                  # Unit tests cho validation, normalization, indexing, buyer pipeline, evaluation
notebooks/                              # Integration test và demo notebooks
scripts/smoke_test_connection.py        # Kiểm tra MongoDB connection và collection counts
scripts/run_search.py                   # CLI search bằng precomputed fixture
scripts/run_evaluation.py               # Full evaluation CLI (hỗ trợ --use-fake-results)
scripts/run_eval_diagnostics.py         # Layer 1 diagnostic probes
scripts/build_eval_pool.py              # Tạo judgment pool cho manual labeling
scripts/import_eval_judgments.py        # Import AI-assisted conservative judgments từ CSV sang JSON
src/query_processor.py                  # Raw query → search-ready fixture (dùng Qwen3:8b + BGE-M3)
src/search_pipeline.py                  # MongoDB hybrid search aggregation
src/retrieval_output.py                 # Explainable output formatting
src/evaluation/                         # Evaluation framework package
evaluation/                             # Evaluation data (queries, probes, judgments)
.env.example                            # Template environment variables
```

---

## 📈 Test 5 — Evaluation Framework

Evaluation framework test không cần MongoDB, Ollama, hay BGE-M3.

### Unit tests (66 tests)

```bash
python -m pytest tests/test_evaluation_dataset.py tests/test_evaluation_metrics.py tests/test_evaluation_diagnostics.py tests/test_evaluation_guardrails.py tests/test_evaluation_runner.py tests/test_evaluation_variants.py tests/test_import_eval_judgments.py -v
```

### Smoke test — Full pipeline không cần external services

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/smoke \
  --use-fake-results
```

Expected output:

```
Evaluation completed in 0.1s
  Results: 750
  Failures: 0
Artifacts written: config, failures, latency, manifest, metrics_by_query, ...
```

### Layer 1 Diagnostics — Kiểm tra query processor

```bash
python scripts/run_eval_diagnostics.py \
  --probes evaluation/queries/diagnostic_probes.json \
  --out .runtime/evaluation/diagnostics
```

### Evaluation Notebook

Mở `notebooks/05_evaluation_retrieval_quality.ipynb`, set `USE_FAKE_RESULTS = True`, Run All Cells.
