# Báo cáo nâng cấp Evaluation Stack

Ngày tạo: 2026-05-29

Repo: `D:/HCPDB/ColdStart_Killer`

## 0. Cập nhật bổ sung sau hardening (2026-05-29)

Sau vòng sửa lỗi quan trọng và dọn contract gần nhất, có 4 điểm cần phản ánh lại trong báo cáo này:

- Đã sửa lỗi wiring `--allow-stale-fixtures`: cờ CLI nay được truyền đúng vào runner/fixture loader.
- Đã sửa logic coverage gate: không còn phụ thuộc variant đầu tiên khi tính `judged_query_count` và `positive_judged_query_count`.
- Đã bỏ cờ CLI dư thừa `--generate-hackathon-report` (report hackathon luôn được ghi theo hành vi thực tế).
- Judge report pack manifest đã tách rõ required và optional static files:
  - `expected_pack_files` chỉ chứa file bắt buộc
  - `optional_static_pack_files` chứa `evaluation_upgrade_report_vi.md`
  - `missing_required_files` và `missing_optional_static_files` tách riêng

## 1. Tóm tắt ngắn

Đợt nâng cấp này làm cho hệ thống evaluation khó bị "nói quá" hơn khi dữ liệu còn mỏng, metric còn thiếu, hoặc claim chưa đủ bằng chứng.

Trọng tâm thay đổi:

- Retrieval metric có thêm so sánh paired giữa các variant, bootstrap CI, blocker cho dữ liệu thưa, và trạng thái `directional_only`.
- Claim reporting không còn chỉ dựa vào raw delta. Muốn claim `supported` phải có đủ judgment gate, metric không null, variant đầy đủ, và paired evidence tích cực.
- Latency được tách rõ thành `search_latency` và `total_path_latency`.
- Personalization qualified CF được gate chặt hơn: cần đủ user, deliberate target, edge/support coverage, không giảm protected metrics, và không re-expose negative items.
- Report có thêm slice confidence, explanation quality diagnostics, lineage/schema metadata, và caveat rõ hơn cho demo/judge-facing reporting.

Không đổi:

- Không đổi tên artifact stability-critical.
- Không đổi claim states: `supported`, `unsupported`, `needs_more_evidence`.
- Không thêm write path cho evaluation dashboard.
- Không bỏ confirmation gate `EVAL_RUN_WRITE`.
- Không bỏ synthetic/demo caveat trong personalization.
- Không đổi variant names hoặc baseline meaning.

## 2. Các file chính đã thay đổi

- `src/evaluation/metrics.py`: thêm paired comparison diagnostics, bootstrap CI, sparse evidence blockers, slice confidence helpers.
- `src/evaluation/runner.py`: thêm `variant_comparisons`, `slice_confidence`, `latency_summary`, `evaluation_schema_version`, `artifact_contract_version`, `input_fingerprints`.
- `src/evaluation/reporting.py`: harden claim gates, tách latency claim, thêm slice confidence/explanation diagnostics vào markdown report.
- `src/evaluation/hackathon_report.py`: thêm caveat cho directional delta và nói rõ search latency không phải total path latency.
- `src/evaluation/explanation_check.py`: thêm missing intent/fact count, both-missing rate, explanation quality label.
- `src/evaluation/personalization_eval.py`: harden `_qualified_cf_gate`.
- `scripts/summarize_evaluation.py`: đọc thêm optional detail artifacts khi regenerate summary.
- Tests liên quan được cập nhật/thêm trong các file `tests/test_evaluation_*`, `tests/test_personalization_evaluation.py`, `tests/test_hackathon_report.py`.

## 3. Vì sao an toàn với repo này

Compatibility được giữ theo hướng additive:

- Các artifact cũ vẫn giữ tên:
  - `metrics_summary.md`
  - `layer2_metrics_summary.json`
  - `layer2_metrics_by_query.csv`
  - `layer2_raw_results.json`
  - `config.json`
  - `manifest.json`
  - `hackathon_impact_report.md`
- Các field mới được thêm vào config/run data, không thay thế field cũ.
- API dashboard vẫn chỉ có read path và vẫn được test bằng fake collection có write-method trap.
- Persisted evaluation run vẫn require confirmation, và CLI dry-run vẫn không ghi artifact nếu không yêu cầu.
- Personalization output vẫn in rõ caveat: synthetic/demo metrics are indicative only.
- Judge pack giữ additive contract, đồng thời tách rõ optional static attachment (`evaluation_upgrade_report_vi.md`) khỏi required pack files.

## 4. Bằng chứng verification

### 4.1 Mandatory evaluation test suite

Command:

```bash
python -m pytest tests/test_evaluation_dataset.py tests/test_evaluation_diagnostics.py tests/test_evaluation_metrics.py tests/test_evaluation_variants.py tests/test_evaluation_runner.py tests/test_evaluation_guardrails.py tests/test_evaluation_persistence.py tests/test_evaluation_polish.py tests/test_personalization_evaluation.py tests/test_api_evaluation_runs.py -q -p no:cacheprovider
```

Kết quả:

- PASS
- `104 passed, 1 warning`
- Warning: Python 3.14 torch/sentence-transformers stability warning, không phải test failure.

Ý nghĩa:

- Khóa lại contract, dataset, diagnostics, metrics, variants, runner, guardrails, persistence, report polish, personalization, và read-only evaluation API.

### 4.2 Retrieval evaluation smoke

Command:

```bash
python scripts/run_evaluation.py --queries evaluation/queries/retrieval_queries_seed.json --judgments evaluation/judgments/retrieval_judgments_seed.json --out .runtime/evaluation/smoke_upgrade_check --use-fake-results
```

Kết quả:

- PASS
- Queries: `50`
- Judgments: `2119`
- Results: `750`
- Failures: `0`
- Artifact names được ghi đúng như trước.

Kiểm tra thêm trong `config.json` smoke:

- `has_variant_comparisons=True`
- `has_slice_confidence=True`
- `latency_summary_keys=['query_processing_latency_ms', 'search_latency_ms', 'total_latency_ms']`
- `artifact_contract_version=1.0`
- `evaluation_schema_version=2.2`

### 4.3 Layer 1 diagnostics smoke

Command:

```bash
python scripts/run_eval_diagnostics.py --probes evaluation/queries/diagnostic_probes.json --out .runtime/evaluation/diagnostics_upgrade_check
```

Kết quả:

- PASS
- Loaded probes: `20`
- Pass rate: `100.0%`
- Có warning môi trường/dependency, không phải failure.

Ý nghĩa:

- Layer 1 diagnostics path vẫn chạy được sau thay đổi.

### 4.4 Personalization dry-run

Command:

```bash
python scripts/run_personalization_evaluation.py --dry-run --no-artifacts
```

Kết quả:

- PASS
- Users: `47`
- Evaluated users: `45`
- Events: `2755`
- Artifacts: skipped
- Evaluation run write: skipped
- Caveat synthetic/demo vẫn được in ra.
- Qualified CF gate: `needs_more_evidence (cf_supported_recommendation_count 0 < 5)`

Ý nghĩa:

- Write guard vẫn an toàn.
- Personalization gate không adopt qualified CF khi chưa có enough supported recommendation coverage.

### 4.5 Optional full test suite

Command:

```bash
python -m pytest tests -q -p no:cacheprovider
```

Kết quả:

- PASS
- `442 passed, 1 warning`

Ý nghĩa:

- Không chỉ evaluation subset, toàn bộ test suite hiện tại vẫn xanh.

## 5. Ví dụ claim bây giờ khó bị nói quá hơn

Trước đây, nếu `hybrid_union` có NDCG@10 cao hơn `title_only`, report có thể dễ tạo cảm giác claim đã mạnh.

Bây giờ:

- Raw delta chưa đủ để claim `supported`.
- Cần paired comparison diagnostic.
- Cần đủ paired query count.
- Cần đủ positive judged pair count.
- Cần CI tích cực, không chỉ mean delta dương.

Ví dụ trong smoke report:

```text
hybrid vs no_cold_boost | directional_only: positive_judged_pair_count 0 < 20 | Directional only; do not treat as supported
```

Nghĩa là report vẫn cho người đọc thấy delta, nhưng không cho phép biến delta đó thành claim mạnh khi evidence chưa đủ.

## 6. Latency integrity

Latency claim đã được tách thành:

- `Live search latency evidence`
- `Live total path latency evidence`

Report cũng ghi rõ:

```text
Search latency is not total path latency.
```

Vì vậy, nếu search nhanh nhưng query processing làm total path chậm, report không còn nhập nhằng thành một claim end-to-end chung.

## 7. Personalization integrity

Qualified CF gate hiện cần tối thiểu:

- `evaluated_user_count >= 10`
- `deliberate_evaluated_user_count >= 5`
- `qualified_directional_edge_count >= 2`
- `cf_supported_recommendation_count >= 5`
- `negative_reexposure_rate == 0`
- Không giảm protected metrics so với current CF.

Dry-run mới nhất trả về:

```text
cf_qualified_gate: needs_more_evidence (cf_supported_recommendation_count 0 < 5)
```

Đây là behavior đúng: không adopt policy khi chưa có đủ recommendation support evidence.

## 8. Rủi ro còn lại

- Bootstrap CI hiện là deterministic/conservative framing, không phải một statistical testing framework đầy đủ.
- Retrieval judgments vẫn có caveat AI-assisted/conservative, chưa phải human-audited ground truth.
- Personalization dry-run dùng live data nên số user/events có thể thay đổi theo thời gian.
- Warning Python 3.14 với torch/sentence-transformers vẫn còn; nên cân nhắc Python 3.10-3.12 cho môi trường ổn định hơn.
- Workspace có các thay đổi unrelated tồn tại từ trước, gồm nhiều file markdown bị delete và `Prompt.md` untracked. Đợt nâng cấp này không đụng hoặc revert các thay đổi đó.

## 9. Kết luận release readiness

- `PHASE_2_COMPLETE`
- `RELEASE_READINESS: READY`
- `CHANGE_IMPACT_SUMMARY: medium`
- `CONTRACT_COMPATIBILITY: preserved`
- `CLAIM_INTEGRITY_STATUS: hardened`

Kết luận ngắn: evaluation stack đã được harden theo hướng an toàn hơn cho demo/judge-facing reporting, đặc biệt ở các điểm dễ overclaim: metric delta, sparse slices, latency scope, và qualified CF personalization.
