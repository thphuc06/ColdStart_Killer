# ColdStart_Killer - Bối cảnh diff so với GitHub (2026-05-27)

## 0) Tóm tắt nhanh
- Đây là một refactor lớn cho luồng enrichment web, trọng tâm là chuyển request từ kiểu chờ đồng bộ sang async có polling.
- Tác động chính không phải là thêm tính năng mới, mà là làm pipeline ổn định hơn khi dữ liệu nhiều, search chậm, hoặc model phản hồi lâu.
- Ngoài luồng chạy, còn có tuning config, hard timeout, fallback, và cập nhật test/UI để khớp với hành vi mới.
- Nếu gửi cho Codex hoặc Claude, phần nên đọc trước là mục 9, 10, 11 và 12.

## 0.1) Cách đọc tài liệu này
- Nếu chỉ cần hiểu “đã đổi gì”: đọc mục 2, 3, 5 và 6.
- Nếu cần hiểu “luồng mới chạy thế nào”: đọc mục 9 và 10.
- Nếu cần đánh giá độ an toàn: đọc mục 11 và 12.
- Nếu cần chuyển tiếp cho người khác: đọc mục 13 để có câu tóm lược ngắn.

## 1) Baseline so sánh
- Remote: `origin = https://github.com/thphuc06/ColdStart_Killer.git`
- Nhánh đang làm việc: `master`
- Upstream: `origin/master`
- Độ lệch commit: `0 ahead / 0 behind` (HEAD trùng commit với GitHub)
- Nghĩa là: toàn bộ khác biệt hiện tại đều là **thay đổi trong working tree local** (chưa commit/push).

## 2) Tổng quan phạm vi thay đổi
- Số file thay đổi: `14`
- Tổng diff: `777 insertions, 69 deletions`
- Nhóm thay đổi chính:
  - Async hóa enrichment request + thêm polling + hard timeout guard.
  - Tuning cấu hình Tavily/LLM để giảm tải.
  - Cập nhật test backend/frontend theo hành vi mới.
  - Cải thiện prompt synthesis và lọc evidence.
 - Bản chất thay đổi: đây là thay đổi hạ tầng xử lý và contract vận hành, không chỉ là chỉnh prompt hay sửa UI.

## 3) Danh sách file thay đổi
1. `.env.example`
2. `frontend/src/components/EnrichmentPanel.tsx`
3. `frontend/src/lib/api.ts`
4. `frontend/src/test/seller-draft-page.test.tsx`
5. `prompts/synthesize_web_enrichment.txt`
6. `src/api/routes_enrichment.py`
7. `src/config.py`
8. `src/enrichment/service.py`
9. `src/enrichment/tavily_client.py`
10. `src/llm_client.py`
11. `tests/test_api_enrichment.py`
12. `tests/test_api_smoke.py`
13. `tests/test_enrichment_service.py`
14. `tests/test_llm_client.py`

## 4) Bối cảnh theo từng file

### `.env.example`
- Thêm cấu hình Ollama:
  - `OLLAMA_NUM_CTX`
  - `OLLAMA_NUM_THREAD`
- Mở rộng bộ tuning enrichment:
  - `WEB_ENRICHMENT_QUERY_LLM_TIMEOUT_SECONDS`
  - `WEB_ENRICHMENT_SYNTHESIS_LLM_TIMEOUT_SECONDS`
  - `WEB_ENRICHMENT_REQUEST_HARD_TIMEOUT_SECONDS`
  - `WEB_ENRICHMENT_MAX_EVIDENCE`
  - `WEB_ENRICHMENT_QUERY_MAX_TOKENS`
  - `WEB_ENRICHMENT_SYNTHESIS_MAX_TOKENS`
  - `WEB_ENRICHMENT_SEARCH_DEPTH`
  - `WEB_ENRICHMENT_INCLUDE_RAW_CONTENT`
  - `WEB_ENRICHMENT_SNIPPET_CHAR_LIMIT`
  - `WEB_ENRICHMENT_BLOCKED_DOMAINS`
  - `WEB_ENRICHMENT_PREFERRED_DOMAINS`
- Điều chỉnh mặc định để profile nhẹ hơn (`MAX_QUERIES` 3 -> 2, synthesis timeout/tokens giảm).

### `src/api/routes_enrichment.py`
- Endpoint `POST /api/enrichment/seller-drafts/{draft_id}/request` thêm query param `wait` (`False` mặc định).
- Truyền `wait_for_completion=wait` xuống service.
- Ý nghĩa:
  - Mặc định: enqueue async, trả về nhanh.
  - Có thể dùng `?wait=true` để chờ kết quả đồng bộ (phục vụ test hoặc debug).

### `src/config.py`
- Dataclass `Settings` thêm trường:
  - `ollama_num_ctx`, `ollama_num_thread`
  - `web_enrichment_search_depth`, `web_enrichment_include_raw_content`, `web_enrichment_snippet_char_limit`
- Thêm parsing env tương ứng trong `get_settings()`.

### `src/llm_client.py`
- `call_qwen()` bổ sung `options` động:
  - `num_ctx` (nếu nằm trong range hợp lệ)
  - `num_thread` (nếu nằm trong range hợp lệ)
- Giữ nguyên `num_predict`, `temperature`.

### `src/enrichment/tavily_client.py`
- `TavilyProvider` thêm tham số cấu hình:
  - `search_depth`
  - `include_raw_content`
  - `snippet_char_limit`
- Chuẩn hóa snippet:
  - Chuẩn hóa whitespace.
  - Cắt theo giới hạn ký tự.
- Ý nghĩa: kiểm soát chất lượng/noise và tài nguyên phần evidence.

### `src/enrichment/service.py` (thay đổi lớn nhất)
- Thêm nhiều helper tuning theo env:
  - timeout query/synthesis
  - max evidence
  - max tokens query/synthesis
  - hard timeout toàn request
- Thêm lọc/rerank evidence theo token overlap + domain policy:
  - hỗ trợ blocked/preferred domains
- Async flow mới:
  - Tạo request ở trạng thái `queued`.
  - Chuyển sang `running` trong worker nền.
  - Kết thúc `completed`/`failed` và cập nhật draft/request.
- Thêm quản lý task nền:
  - `_BACKGROUND_ENRICHMENT_TASKS`
  - `_track_background_task(...)`
- Thêm hard-timeout guard cho job:
  - quá hạn -> request `failed` thay vì treo vô hạn.
- Vẫn giữ mode đồng bộ cho test:
  - `wait_for_completion=True` khi gọi qua wrapper sync.

### `frontend/src/components/EnrichmentPanel.tsx`
- Thêm polling tự động khi request status là `queued/running`:
  - Gọi `getEnrichmentRequest(requestId)` mỗi 2s.
  - Dừng polling khi `completed/failed/applied`.
- Mục đích: UX không cần F5, panel tự cập nhật theo tiến độ async.

### `frontend/src/lib/api.ts`
- Sửa thứ tự merge trong `fetchJson()`:
  - Đảm bảo `Content-Type: application/json` không bị mất khi merge `init`.
- Giải quyết bug request body JSON bị parse sai ở backend.

### `frontend/src/test/seller-draft-page.test.tsx`
- Thêm regression test:
  - Kiểm tra request create draft có cả `Authorization` và `Content-Type: application/json`.

### `prompts/synthesize_web_enrichment.txt`
- Prompt được nâng cấp rõ hơn:
  - Rule trust model rõ ràng.
  - Bắt buộc shape JSON chặt chẽ.
  - Nâng yêu cầu `enriched_description` (nội dung đầy hơn, grounded hơn).
  - Hướng dẫn `key_facts` chi tiết (field, confidence, source_urls).

### `tests/test_api_enrichment.py`
- Nhiều case cập nhật sang `request?...wait=true` để deterministic.
- Mục đích: test không phụ thuộc polling async khi assert kết quả completed.

### `tests/test_api_smoke.py`
- Cập nhật kỳ vọng 2 test sang `403` (auth-first guard), thay vì kỳ vọng payload disabled `200`.

### `tests/test_enrichment_service.py`
- Thêm test cho `select_relevant_evidence(...)`:
  - Bỏ qua blocked domains nếu có alternative tốt hơn.
  - Vẫn giữ blocked domain làm last resort nếu không có nguồn nào khác.

### `tests/test_llm_client.py`
- Thêm test xác minh `call_qwen()` forward `num_ctx` và `num_thread` khi config có giá trị hợp lệ.

## 5) Kết quả xác minh đã chạy
- Full backend pytest: `421 passed, 1 warning`.
- Frontend UI tests: `35 passed`.
- Lưu ý runtime noisy E2E:
  - Async enqueue + poll đã hoạt động (quan sát `queued -> completed` trên một số case).
  - Vẫn có case chạy rất lâu trên máy local, nên đã bổ sung hard-timeout guard để không treo vô hạn.

## 6) Tác động hành vi hệ thống
- Trước đây: endpoint request enrichment có thể giữ kết nối HTTP rất lâu.
- Bây giờ:
  - Mặc định endpoint request trả nhanh với `status=queued`.
  - Client/UI poll endpoint detail để lấy kết quả.
  - Hệ thống có hard timeout để fail-safe nếu job bị kẹt.

## 7) Đề xuất cho người tiếp theo
1. Nếu cần so sánh profile hiệu năng/chính xác, chạy batch noisy có timeout per-case và ghi metric p50/p95.
2. Nếu muốn release an toàn hơn, cảnh báo trong runbook rằng `request` là async và phải poll.
3. Cân nhắc thêm observability (log structured cho transition queued/running/completed/failed).

## 8) Lệnh tái tạo so sánh
- `git fetch origin`
- `git rev-list --left-right --count origin/master...HEAD`
- `git diff --name-status origin/master`
- `git diff --stat origin/master`

---
Generated locally on 2026-05-27 for handover/context tracking.

## 9) Luồng xử lý trước và sau
- Trước đây, `POST /api/enrichment/seller-drafts/{draft_id}/request` có xu hướng giữ kết nối HTTP cho tới khi cả pipeline hoàn tất, nên khi query planning, Tavily search hoặc synthesis chậm thì request dễ bị treo lâu hoặc timeout.
- Bây giờ, request mặc định được tạo ở trạng thái `queued`, lưu `request_id` ngay, rồi worker nền mới chạy các bước nặng.
- Luồng mới đi theo thứ tự: tạo request `queued` -> đổi sang `running` -> lập kế hoạch query -> search evidence -> lọc evidence phù hợp -> synthesis -> cập nhật request/draft -> kết thúc `completed` hoặc `failed`.
- Frontend không còn chờ một response duy nhất để biết kết quả cuối cùng; nó poll `GET /api/enrichment/requests/{request_id}` cho tới khi trạng thái ổn định.
- `?wait=true` vẫn được giữ để test hoặc debug khi cần kết quả đồng bộ ngay trong một lần gọi.
- Cơ chế hard timeout được thêm vào để ngăn job chạy vô hạn: nếu vượt ngưỡng, request được đánh dấu `failed` thay vì treo mãi.

## 10) Chi tiết kỹ thuật đáng chú ý
- `src/enrichment/service.py` là phần thay đổi lớn nhất, vì nó vừa điều phối pipeline, vừa quản lý trạng thái request, vừa ghi dữ liệu vào draft/request collections.
- `select_relevant_evidence(...)` không chỉ lấy kết quả search theo điểm số thô, mà còn chấm thêm theo token overlap với `title`, `brand`, `category_id` và `features` của draft để ưu tiên evidence liên quan hơn.
- Danh sách domain bị chặn và domain ưu tiên được đọc từ env, nên môi trường deploy có thể điều chỉnh chính sách evidence mà không cần sửa code.
- `_build_queued_request_doc(...)` chuẩn hóa document ban đầu cho request, để ngay khi tạo ra đã có đầy đủ field cần thiết cho UI và API detail.
- `_complete_request_web_enrichment(...)` là nơi thực sự chạy toàn bộ pipeline, cập nhật `requests_collection` và `drafts_collection`, đồng thời chuyển trạng thái request/draft qua các mốc `running`, `completed`, `failed`.
- Nếu query planner hoặc synthesis bị timeout, service không bỏ cuộc ngay mà dùng fallback nhẹ hơn để vẫn trả về kết quả hợp lệ nếu có thể.
- `src/enrichment/tavily_client.py` giờ có thêm `search_depth`, `include_raw_content` và `snippet_char_limit`, nên payload search có thể tinh chỉnh theo môi trường thực tế.
- `src/llm_client.py` chỉ forward `num_ctx` và `num_thread` khi giá trị nằm trong range an toàn, để tránh cấu hình sai làm hỏng call đến Ollama.
- `prompts/synthesize_web_enrichment.txt` được siết chặt hơn về output JSON, độ dài `enriched_description`, và yêu cầu `source_urls` phải bám đúng evidence.
- `frontend/src/components/EnrichmentPanel.tsx` poll mỗi 2 giây và dừng khi trạng thái terminal, vì vậy UI phản ánh tiến trình async mà không cần người dùng refresh tay.
- `frontend/src/lib/api.ts` được sửa thứ tự merge `fetchJson()` để header `Content-Type: application/json` không bị mất khi truyền `init`.

## 11) Phạm vi kiểm tra và ý nghĩa của nó
- Backend test suite chạy xanh với `421 passed, 1 warning`.
- Frontend test suite chạy xanh với `35 passed`.
- Điều này quan trọng vì refactor lần này không chỉ là đổi config; nó đụng vào orchestration chính của enrichment, nên việc suite xanh cho thấy contract cũ/mới vẫn khớp ở mức hành vi.
- Các test `wait=true` giúp giữ phần xác minh deterministic, không phụ thuộc vào timing của background task.
- Smoke tests được cập nhật sang kỳ vọng `403` cho các route bảo vệ theo auth-first, nên không còn hiểu nhầm response disabled cũ là hành vi đúng nữa.
- Lưu ý runtime noisy E2E: đã quan sát được luồng `queued -> completed` ở một số case, nhưng vẫn có case rất chậm trên máy local, nên hard timeout là phần bảo hiểm quan trọng.

## 12) Rủi ro và giới hạn cần nói rõ
- `request` giờ là async mặc định, nên client nào muốn kết quả cuối phải biết poll request detail hoặc dùng `wait=true`.
- Nếu không cấu hình các env mới, hệ thống vẫn chạy với default an toàn, nhưng tuning sẽ chưa tối ưu cho mọi môi trường.
- `WEB_ENRICHMENT_BLOCKED_DOMAINS` nếu đặt quá chặt có thể loại mất nguồn evidence tốt, đặc biệt là nguồn video/social.
- `WEB_ENRICHMENT_INCLUDE_RAW_CONTENT=true` có thể tăng noise và chi phí xử lý, nên chỉ bật khi cần.
- Hard timeout giúp không treo vô hạn, nhưng cũng có nghĩa là job quá lâu sẽ bị fail thay vì chờ tiếp; nếu muốn ưu tiên accuracy hơn latency thì phải tăng ngưỡng này có kiểm soát.
- `wait=true` chỉ nên dùng cho test, debug hoặc các luồng nội bộ cần đồng bộ; không nên biến nó thành cách gọi mặc định cho tải lớn.
- Phần report này chỉ mô tả thay đổi local so với `origin/master`; không suy diễn thêm về PR, tag hay commit lịch sử upstream ngoài những gì đã đo được.

## 13) Nếu bạn cần gửi cho người khác
- Câu mở đầu ngắn gọn có thể dùng là: “Repo này vừa refactor lớn phần enrichment, chuyển request xử lý từ đồng bộ sang async có polling, kèm tuning config, timeout guard và cập nhật test/UI.”
- Nếu người nhận là dev, nên cho họ đọc phần 9 và 10 vì đó là chỗ mô tả đúng luồng và các điểm kỹ thuật quan trọng.
- Nếu người nhận là PM hoặc người không viết code, chỉ cần phần 1, 2, 5, 6 và 13 là đã đủ để hiểu vì sao thay đổi này quan trọng.
- Nếu muốn một bản cực ngắn để forward qua chat, có thể rút thành 3 ý: async hóa để ổn định hơn, thêm polling để UI theo kịp trạng thái thật, và thêm timeout/fallback để tránh treo.
