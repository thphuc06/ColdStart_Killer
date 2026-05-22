# PLAN: Instrumentation Cold-Start Window + Live Evaluation / A-B Test

Trạng thái: Nháp (triển khai được khi chốt Open Questions)
Owner: TBD
Cập nhật lần cuối: 2026-05-22
Phiên bản: v1.0

## 0) Tóm tắt nhanh

Mục tiêu là đo được cold-start window trên traffic thật và xác thực tác động bằng live evaluation hoặc A/B test. Plan này bổ sung đầy đủ: data contract, schema sự kiện, logic dedup, sampling, phân tích thống kê, guardrails, và runbook rollback.

## 1) Mục tiêu và tiêu chí thành công

### Mục tiêu A: Đo được cold-start window trên traffic thật
Cần có timestamp tin cậy để trả lời:
- Mất bao lâu từ lúc item được tạo đến khi được index?
- Mất bao lâu từ lúc index đến khi lần đầu xuất hiện trong top-K?
- Mất bao lâu từ lúc xuất hiện đến click / purchase đầu tiên?

Tiêu chí thành công:
- >= 95% item mới có indexed_at trong vòng 24h sau created_at
- >= 90% item mới có first_seen_in_top_k_at trong vòng 72h sau indexed_at
- Time-to-first-click và time-to-first-purchase đo được (không null) cho >= 70% item có impression

### Mục tiêu B: Xác thực tác động bằng live evaluation hoặc A/B test
Tiêu chí thành công (ví dụ):
- CTR@10 tăng >= +2% tương đối (p < 0.05)
- Conversion rate tăng >= +1% tương đối (p < 0.05)
- Time-to-first-relevant (TTFR) giảm >= 5% (p < 0.05)
- Guardrails: P95 latency không tăng > 10%, zero-results rate không tăng > 0.5%

## 2) Scope, Non-goals, Assumptions

### Scope
- Instrumentation ở catalog/indexer, search API, client tracking
- Data pipeline lưu events và tính metrics
- Live evaluation + A/B test cho cold-start exposure và chất lượng search

### Non-goals
- Không tối ưu model hoặc thuật toán retrieval
- Không thay đổi ranking logic trong production
- Không can thiệp UI/UX ngoài logging

### Assumptions
- Có quyền log server-side và client-side events
- Có data warehouse hoặc storage theo ngày
- Có experiment flagging để bật/tắt variant

## 3) Định nghĩa và quy ước

### Định nghĩa cold item
- Cấu hình mặc định: is_cold_item = true nếu interaction_count < N hoặc age_days < M
- N, M là tham số cấu hình (chốt ở Open Questions)

### Định nghĩa TTFR (time-to-first-relevant)
- Relevance proxy mặc định: click + dwell_time >= 10s hoặc add-to-cart
- Nếu có judgments, TTFR = time từ search đến click có relevance >= 2

### Quy ước định danh
- request_id: unique cho 1 lần search
- session_id: ổn định trong 1 session
- user_id_hash: hash 1 chiều, không lưu raw ID
- event_id: unique cho mỗi event (UUID)

## 4) Instrumentation Plan và Data Contract

### 4.1 Nguyên tắc
- Bắt buộc server-side logging để tránh thiếu dữ liệu
- Client logs dùng để đo impression/click/conversion
- Có event_version và schema_version để backward compatibility
- Dedup dựa trên event_id + request_id + item_id

### 4.2 Sự kiện vòng đời item (catalog + indexer)

Events:
- item_created
- item_indexed
- item_updated (tùy chọn)

Schema tối thiểu:
- event_id (string, UUID)
- event_version (int, default 1)
- emitted_at (timestamp, UTC)
- item_id (string)
- created_at (timestamp)
- indexed_at (timestamp, chỉ có ở item_indexed)
- seller_id_hash (string)
- category_id (string)
- price_bucket (string)
- is_cold_item (bool)
- ingestion_source (string)

### 4.3 Search results logging (server-side)

Event: search_results
Schema tối thiểu:
- event_id
- event_version
- emitted_at
- request_id
- session_id
- user_id_hash
- query_text (tùy policy, có thể hash hoặc drop)
- query_id (nếu map vào evaluation queries)
- language
- top_k
- pipeline_variant (control/treatment)
- latency_ms
- empty_result (bool)
- results[]:
	- item_id
	- rank
	- score
	- is_cold_item
	- channels
	- matched_intent
	- matched_fact

### 4.4 Impression logging (client-side)

Event: search_impression
Schema tối thiểu:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- rank
- viewport_percent (0-100)

### 4.5 Click logging (client-side)

Event: search_click
Schema tối thiểu:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- rank
- dwell_time_ms (nếu có)

### 4.6 Conversion logging

Event: search_purchase
Schema tối thiểu:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- order_id
- revenue

## 5) Data Model và lưu trữ

### Bảng item_lifecycle
- item_id (PK)
- created_at
- indexed_at
- seller_id_hash
- category_id
- price_bucket
- is_cold_item
- ingestion_source

### Bảng search_results
- request_id (PK)
- user_id_hash
- session_id
- query_text (nullable)
- query_id
- language
- timestamp
- top_k
- pipeline_variant
- latency_ms
- empty_result
- results (array)

### Bảng search_impressions, search_clicks, search_purchases
- request_id
- item_id
- user_id_hash
- session_id
- timestamp
- rank
- dwell_time_ms (click)
- order_id, revenue (purchase)

Partitioning:
- Partition theo ngày
- Index theo request_id, item_id, user_id_hash

Retention:
- Raw events: 90 ngày
- Aggregates: 12 tháng

## 6) Tính toán metrics

### Cold-start window (per item)
- time_to_indexed = indexed_at - created_at
- time_to_first_seen_top_k = min(search_results.timestamp) - indexed_at
- time_to_first_impression = min(search_impressions.timestamp) - first_seen_in_top_k_at
- time_to_first_click = min(search_clicks.timestamp) - first_seen_in_top_k_at
- time_to_first_purchase = min(search_purchases.timestamp) - first_seen_in_top_k_at

### Exposure và relevance proxy
- cold_exposure_rate@K = impressions_of_cold_items / total_impressions
- cold_ctr@K = clicks_on_cold_items / impressions_of_cold_items
- cold_conversion@K = purchases_of_cold_items / impressions_of_cold_items

### Quality metrics cho live evaluation
- CTR@K, Conversion@K, TTFR, zero-results rate, P50/P95 latency

## 7) Data Quality, Monitoring, Backfill

### Checks bắt buộc
- completeness: % events có request_id, item_id
- freshness: độ trễ ingest < 15 phút
- null rate: indexed_at, first_seen_in_top_k_at
- outliers: time_to_indexed > 7 ngày

### Monitoring
- Dashboard daily cho cold-start window
- Alert khi null rate > 10% hoặc latency spike > 20%

### Backfill
- Nếu thiếu indexed_at: backfill từ indexer logs
- Nếu thiếu impressions: fallback từ search_results (rank <= 10)

## 8) Live Evaluation Plan

### Setup
- MongoDB live
- Tắt cached fixtures
- Bật logging search_results

### Sampling
- 200-500 queries từ traffic thật
- Coverage theo slice: VN, EN, price_filter, compatibility

### Acceptance checks
- Failure count = 0
- Latency sample count >= 50
- Coverage log >= 90%

## 9) A/B Test Plan

### Thiết kế thí nghiệm
- Unit: user_id_hash (hoặc session_id nếu anonymous)
- Randomization: 50/50 control vs treatment
- Thời lượng: 1-2 tuần hoặc đến khi đủ sample size

### Sample size (ước lượng)
- n/arm ~ 2 * (Z_alpha/2 + Z_beta)^2 * p * (1-p) / delta^2
- Ví dụ CTR baseline = 0.08, delta = 0.002 (2.5% relative), alpha=0.05, power=0.8
- n/arm xấp xỉ 120k sessions

### Primary KPIs
- CTR@10
- Conversion@10
- TTFR

### Secondary KPIs
- Zero-results rate
- Average rank of clicked item
- Revenue per search

### Guardrails
- P95 latency <= +10%
- Error rate <= baseline +0.2%
- Zero-results rate <= baseline +0.5%

### Phân tích
- CTR/Conversion: two-proportion z-test hoặc bootstrap
- TTFR: Mann-Whitney U hoặc bootstrap
- Báo cáo effect size + confidence interval
- Kiểm soát multiple comparisons bằng Benjamini-Hochberg

### Quy tắc quyết định
- Ship nếu tất cả primary KPIs cải thiện và không có guardrail regression
- Rollback nếu guardrail vượt ngưỡng hoặc effect size âm

## 10) Rollout và Runbook

### Rollout
- 10% -> 50% -> 100% (mỗi bước 24-48h)
- Dừng nếu P95 latency tăng > 10% hoặc CTR giảm > 1%

### Runbook
- Nếu log thiếu: kiểm tra event pipeline, schema version, dedup rules
- Nếu CTR giảm: kiểm tra slice breakdown và cold exposure rate
- Nếu conversion giảm: kiểm tra attribution window và sessionization

## 11) Rủi ro và giảm thiểu

- Thiếu timestamp -> bổ sung logging server-side
- Lo ngại PII -> hash user_id, hạn chế log query_text
- Conversion thưa -> kéo dài test hoặc chọn segment traffic cao hơn
- Data drift -> thêm monitor theo category và price bucket

## 12) Checklist triển khai

Instrumentation:
- [ ] Add event item_indexed trong indexer
- [ ] Add search_results logging trong API
- [ ] Add impression/click/purchase events
- [ ] Verify schema và dedup rules trong data warehouse

Live evaluation:
- [ ] Chạy live evaluation với fresh fixtures
- [ ] Export metrics_summary + latency

A/B test:
- [ ] Setup experiment flagging
- [ ] Validate exposure split
- [ ] Run test và phân tích kết quả

## 13) Timeline đề xuất

- Tuần 1: Instrumentation server-side + client-side
- Tuần 2: Data pipeline + QA checks
- Tuần 3: Live evaluation (200-500 queries)
- Tuần 4-5: A/B test + phân tích

## 14) Câu hỏi mở

- Định nghĩa chính thức của cold item là gì (time since creation hay interaction count)?
- Policy privacy cho logging query_text là gì?
- Attribution window cho purchase là bao lâu (24h, 7d)?
- Có cần hỗ trợ đa khu vực (timezone, locale) không?
