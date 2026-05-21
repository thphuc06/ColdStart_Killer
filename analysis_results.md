# 📋 Review: Notebook 05 — Evaluation Retrieval Quality

## Verdict: ⚠️ Notebook chạy thành công nhưng có 2 vấn đề cần xử lý

---

## ✅ Những phần chạy đúng

| Phần | Trạng thái | Ghi chú |
|---|---|---|
| Startup check | ✅ OK | Python 3.14, tất cả packages đều có |
| Configuration | ✅ OK | `USE_FAKE_RESULTS=False`, live MongoDB |
| Imports (Cell A) | ✅ OK | Tất cả evaluation modules load thành công |
| Data loading (Cell B) | ✅ OK | 20 probes, 50 queries loaded |
| **Layer 1 — Diagnostics** | ✅ **100% pass** | 14/14 testable probes pass, 4 known_risk (documented), 2 unsupported (planned) |
| Variants: vector_only, bm25_only, hybrid_union, hybrid_no_cold_boost | ✅ OK | Tất cả 4 variant này chạy tốt, trả kết quả |
| Latency | ✅ OK | P50=85ms, P95=152ms — tốt cho production |
| Artifact output | ✅ OK | 8 files ghi ra `.runtime/evaluation/notebook_run/` |

---

## ❌ Vấn đề 1: `title_only` variant fail 100% (50/50 queries)

> [!CAUTION]
> **Toàn bộ 50 failures đều đến từ `title_only` variant** — không phải từ các variant khác.

**Lỗi MongoDB:**
```
OperationFailure: Invalid $project :: caused by :: 
Cannot do exclusion on field fusion_score in inclusion projection
```

**Nguyên nhân gốc:** Trong file [variants.py](file:///d:/HCPDB/ColdStart_Killer/src/evaluation/variants.py#L181-L215), hàm `_title_only_pipeline()` có `$project` stage chứa lẫn inclusion và exclusion:

```python
# Dòng 207-208 — ĐÂY LÀ LỖI:
"rank_vector": None,    # MongoDB coi None = exclusion (0)
"rank_bm25": None,      # MongoDB coi None = exclusion (0)
"fusion_score": 0,      # MongoDB coi 0 = exclusion
```

MongoDB không cho phép trộn inclusion (`"title": "$title_en"`, `"brand": 1`) với exclusion (`"fusion_score": 0`) trong cùng một `$project` stage.

**Fix đề xuất:**
```python
# Thay None/0 bằng literal values:
"rank_vector": {"$literal": None},
"rank_bm25": {"$literal": None},
"fusion_score": {"$literal": 0},
```

---

## ⚠️ Vấn đề 2: Không có Relevance Judgments → Metrics = N/A hoặc 0

> [!IMPORTANT]
> File [retrieval_judgments_seed.json](file:///d:/HCPDB/ColdStart_Killer/evaluation/judgments/retrieval_judgments_seed.json) chứa `[]` (mảng rỗng).

**Hậu quả:**
- **NDCG@10, Recall@10** = `N/A` cho tất cả variants (cần judgments để tính)
- **MRR@10, Precision@5, HitRate@10, ColdRelevantRate@10** = `0.0` (vì không doc nào được đánh "relevant")
- **Claim Status**: 0 supported, 1 unsupported, 5 needs_more_evidence
- Đây là **hành vi đúng** — notebook đã warn: `"⚠️ No judgments loaded"`

**Đây không phải lỗi code** — chỉ là chưa có data judgments. Notebook đã ghi rõ next step.

---

## 📊 Tổng hợp kết quả thực tế

### Layer 1 — Diagnostics: ✅ Excellent
- 14/14 pass, 0 fail
- 4 known_risk (tiếng Việt không dấu, price format `1.5M VND`) — documented đúng
- 2 expected_unsupported (negation) — đúng kế hoạch

### Layer 2 — IR Metrics: ⚠️ Incomplete
- 4/5 variants chạy OK, `title_only` fail do bug `$project`
- 1,935 results trả về (50 queries × ~10 results × 4 variants thành công ≈ hợp lý)
- **Metrics chưa có ý nghĩa** vì thiếu judgments

### Layer 3 — Demo Readiness: ⚠️ Not ready yet
- Latency tốt (Search P50=85ms, P95=152ms) — phản hồi nhanh
- Claims chưa supported — cần judgments + fix title_only

---

## 🔧 Next Steps — Ưu tiên

### 1. Fix bug `title_only` `$project` (5 phút)
Sửa file [variants.py](file:///d:/HCPDB/ColdStart_Killer/src/evaluation/variants.py#L205-L209):

```diff
 "$project": {
     "_id": 0,
     "item_id": "$_id",
     "title": "$title_en",
     "brand": 1,
     "category_id": 1,
     "price_vnd": 1,
     "price_bucket": 1,
     "is_cold_item": "$cold_start.is_cold_item",
     "score": "$match_score",
     "matched_intent": "",
     "matched_fact": "",
-    "rank_vector": None,
-    "rank_bm25": None,
-    "fusion_score": 0,
+    "rank_vector": {"$literal": None},
+    "rank_bm25": {"$literal": None},
+    "fusion_score": {"$literal": 0},
     "debug": {
         "matched_channels": [],
         "variant": "title_only",
     },
 }
```

### 2. Tạo Relevance Judgments (cần thời gian label)
```bash
python scripts/build_eval_pool.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --out .runtime/evaluation/pool \
  --top-k 20
```
Sau đó label relevance (0-3) trong file `judgment_pool.csv` và copy vào `retrieval_judgments_seed.json`.

### 3. Re-run notebook sau khi fix

---

## 💡 Về notebook — cần giải thích gì thêm?

Notebook viết khá tốt, có mấy điểm nhỏ có thể cải thiện:

1. **Nên thêm 1 cell giải thích kết quả 0.0**: Khi metrics toàn 0.0 mà không có annotation, người đọc có thể nhầm tưởng pipeline trả sai. Nên thêm markdown cell giải thích "Metrics = 0.0 because no relevance judgments are loaded. This is expected behavior."

2. **Deep Dive section chỉ show 2 variants**: Cell `q001` deep dive chỉ hiện `bm25_only` và `hybrid_no_cold_boost` (20 rows max). Không thấy `vector_only` hay `hybrid_union`. Nên tăng limit hoặc ghi chú rằng output bị truncate.

3. **Failure Summary nên phân biệt variant**: Hiện chỉ ghi `aggregation_failed: 50` — nên thêm cột variant để rõ 50 lỗi này đều từ `title_only`.
