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
| pip install -r requirements.txt | ✅ | ⚠️ chỉ cần pymongo pydantic python-dotenv pytest requests numpy |

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
pip install pymongo pydantic python-dotenv pytest requests numpy
```

### Bước 2 — Tạo file .env

Tạo file `.env` ở repo root:

```bash
MONGODB_URI="mongodb+srv://<username>:<password>@<cluster-url>/?retryWrites=true&w=majority"
MONGODB_DB_NAME="coldstart_killer"
OLLAMA_MODEL="qwen3:8b"
BRAVE_API_KEY=""
EMBEDDING_MODEL="BAAI/bge-m3"
USE_CUDA=true
EMBEDDING_STORAGE_FORMAT="list_float"
DEFAULT_INDEX_LIMIT=50
M0_SAFE_LIMIT=3000
DEDICATED_FULL_LIMIT=5000
MONGODB_TIMEOUT_MS=10000
```

⚠️ KHÔNG commit `.env` lên GitHub.

### Bước 3 — Verify kết nối MongoDB

```bash
python scripts/smoke_test_connection.py --counts
```

Expected output ví dụ:

```bash
MongoDB connection: OK
Database: coldstart_killer
items: 1610
retrieval_units: 16332
```

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
| tests/test_indexing.py | indexing | ✅ requires Ollama |
| tests/test_llm_propositions.py | LLM propositions | ✅ requires Ollama |

---

## 🏥 Test 2 — Integration Health Test (Notebook 03)

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

Notebook này chạy full demo từ user query thật → kết quả. Test này cần máy teammate vì có translation bằng Qwen3 và embedding bằng BAAI/bge-m3.

### Cách chạy

1. Mở `notebooks/04_demo_buyer_search.ipynb`
2. Vào Cell 3 — đổi QUERY:

```python
QUERY = "tai nghe chống ồn dưới 500k"  # ← đổi query ở đây
TOP_K = 10
```

3. Run All Cells

### Query examples để test

| Query | Ngôn ngữ | Filter | Mục đích test |
|-------|----------|--------|---------------|
| "tai nghe chống ồn dưới 500k" | Tiếng Việt | price_max | Vietnamese + price filter |
| "moisturizing cream for dry skin" | English | none | English query, beauty category |
| "phone case samsung galaxy s22 under 300k" | English | price_max | Price filter, electronics |
| "wireless charger iphone 14" | English | none | Simple product search |
| "váy đầm dự tiệc đẹp" | Tiếng Việt | none | Vietnamese fashion |

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
  "original_query": "Raw user query for traceability",
  "language_detected": "vi or en",
  "english_query": "English query after translation if needed",
  "hype_search_query_en": "Semantic HyPE-style query text",
  "bm25_search_query_en": "Keyword-optimized BM25 query text",
  "hard_filters": {
    "in_stock": true,
    "price_max": 500000,
    "max_price_vnd": 500000,
    "category_id": "all_electronics"
  },
  "query_embedding": [0.123, 0.456, 0.789]
}
```

Note: fixture phải có `query_embedding` được tạo bởi BAAI/bge-m3.

---

## ✅ Checklist trước khi Demo

- [ ] MongoDB connected (smoke_test_connection PASS)
- [ ] Data indexed (items >= 1000, retrieval_units >= 10000)
- [ ] Atlas vector_index status: READY
- [ ] Atlas text_index status: READY
- [ ] Ollama running (ollama serve)
- [ ] Qwen3:8b pulled (ollama pull qwen3:8b)
- [ ] BGE-M3 downloaded
- [ ] Notebook 03 all PASS
- [ ] Notebook 04 runs end-to-end with sample query

---

## 🗂️ Cấu trúc repo liên quan đến testing

```bash
tests/                                  # Unit tests cho validation, normalization, indexing, buyer pipeline
notebooks/                              # Integration test và demo notebooks
scripts/smoke_test_connection.py        # Kiểm tra MongoDB connection và collection counts
scripts/run_search.py                   # CLI search bằng precomputed fixture
src/query_processor.py                  # Raw query → search-ready fixture
src/search_pipeline.py                  # MongoDB hybrid search aggregation
src/retrieval_output.py                 # Explainable output formatting
.env.example                            # Template environment variables
```
