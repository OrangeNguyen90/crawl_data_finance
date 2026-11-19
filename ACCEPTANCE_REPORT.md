# Nghiệm thu triển khai V2.0 — 2026-11-04

**Trạng thái chung: CHƯA ĐẠT nghiệm thu production đầy đủ.**

## Cập nhật sau xử lý database chưa tồn tại

Đã tạo database PostgreSQL cấu hình, áp dụng toàn bộ migrations đến 0004,
probe PostgreSQL PASS, Django system check PASS và **74 tests passed trên PostgreSQL**
trong database test có tên UUID riêng, tách khỏi database vận hành.
bootstrap_database chạy lại không tạo lại/xóa database. Đã đăng ký sáu nguồn.
Secrets local chuyển sang .env được ignore; settings tự nạp .env và ưu tiên environment.
Chưa nhập market observations vào PostgreSQL. CME/Eurex và các giới hạn nguồn vẫn còn.

Các ghi chú PostgreSQL chưa kết nối bên dưới là nhật ký của lần nghiệm thu trước
khi tạo database; trạng thái connection/migrations/test mới nhất là phần cập nhật này.

Đã sửa repository, thêm collectors/importers, quality engine, API, dashboard,
queue/scheduler và tests. PostgreSQL chưa kết nối được; CME/Eurex và một số phạm vi
nguồn còn giới hạn thực tế. Không đánh dấu toàn bộ MASTER PROMPT là hoàn thành.

## Kết quả kiểm chứng

| Check | Kết quả | Phạm vi |
|---|---|---|
| Baseline tests | 5 passed | SQLite test backend ban đầu |
| Bộ test sau nâng cấp | 74 passed | Unit/integration, gồm fixture nguồn thật; không đồng nghĩa mọi nguồn live PASS |
| Django check | Không lỗi | Cấu hình local |
| Django check --deploy | Không lỗi | Production env + secret tạm riêng cho check; không deploy |
| Migration drift | No changes detected | 0001 giữ nguyên; 0002–0004 additive |
| Migration execution | Đã chạy | Database SQLite nghiệm thu mới; PostgreSQL chưa chạy |
| OpenAPI generation/validation | Đạt | [openapi.yaml](./openapi.yaml) |
| PostgreSQL connection | FAIL / OperationalError | Không in connection string hoặc secret |
| Full CFTC 2025 parse/replay | 69.888 rows; 0 rejected | Sáu loại archive tải thật |
| Repeat replay | 0 writes mới | SHA + phạm vi checkpoint |
| Cboe replay | 12 product aggregates | Totals khớp; chưa contract detail |
| FirstRate sample import | 16.232 rows; 0 rejected | Public sample riêng tư, không full history |
| Dashboard/API acceptance DB | 86.132 market rows | Browser snapshot + authenticated client |
| CSV/Parquet export | 69.888 COT rows | Parquet giữ positions JSON; Decimal/UTC được test |
| Quality scan | 997 WARNING; 0 ERROR/CRITICAL được phát hiện | 994 gaps cần đối chiếu; không certify full coverage |

Không xóa dữ liệu hiện có, không recreate migration 0001, không thay PostgreSQL bằng
SQLite trong môi trường chính. Database nghiệm thu nằm ở temp riêng. Production
records nhập thành công trong phiên: **0**.

## Nhật ký theo STEP

### STEP 1 — Audit

- File: [AUDIT_REPORT.md](./AUDIT_REPORT.md).
- Đọc settings/models/collectors/commands/API/admin/migration/tests/dependencies.
- Kiểm tra database bằng [probe](./scripts/probe_database.py), không lộ secret.
- Kết quả: audit hoàn thành; PostgreSQL connection chưa đạt; chưa có Git metadata.
- Records nhập: 0. Tiếp theo: cấu hình connection hợp lệ rồi kiểm chứng PostgreSQL.

### STEP 2 — Baseline

- Chưa sửa nghiệp vụ khi chạy bộ test gốc: 5 passed.
- Django system check sạch; model/migration không drift.
- Records nhập production: 0. Các record test thuộc test database tách biệt.
- Tiếp theo: tái hiện bug trước khi patch.

### STEP 3 — Sửa lỗi được xác nhận

- Files: [settings](./config/settings.py), [models](./marketdata/models.py),
  [BaseCollector](./marketdata/collectors/base.py), [runtime](./marketdata/runtime.py),
  [logging](./marketdata/logging.py), migrations
  [0002](./marketdata/migrations/0002_collector_runtime.py),
  [0003](./marketdata/migrations/0003_data_integrity.py).
- Tests: [pipeline regression](./marketdata/tests/test_pipeline.py),
  [HTTP/job tests](./marketdata/tests/test_jobs_http.py),
  [hardening](./marketdata/tests/test_hardening.py).
  [Batch duplicate tests](./marketdata/tests/test_duplicate_batches.py) kiểm tra xung đột qua ranh giới batch và counter của duplicate giống hệt.
- Đã tái hiện 5 regression failures trước sửa. Checkpoint coverage, exception
  isolation, disabled-source check và CSV shape được sửa.
- Null-expiration unique constraint có preflight; không tự gộp duplicates.
- Records production: 0. PostgreSQL transaction semantics vẫn cần test thật.

### STEP 4 — CFTC

- Files: [collector](./marketdata/collectors/cftc.py),
  [sync command](./marketdata/management/commands/sync_source.py),
  [backfill command](./marketdata/management/commands/backfill_source.py),
  [archive replay](./marketdata/management/commands/import_cftc_archive.py),
  [live check](./marketdata/tests/live_cftc.py), [fixtures](./marketdata/tests/fixtures/README.md).
- Report family/scope/date consistency, raw fields, + market codes, -0, cp1252,
  bounded ZIP/CSV, per-file rollback, quarantine, bulk upsert và source revision.
- Tests: baseline + pipeline + hardening + sáu actual-source schema fixtures.
- Real-source acceptance import: 69.888; rerun 0 writes. Production 0.
- Giới hạn: chưa certify mọi năm lịch sử; weekly refresh dùng annual archives.
- Tiếp theo: PostgreSQL replay và nguồn/network theo lịch thực tế.

### STEP 5 — CME

- Files: [CME](./marketdata/collectors/cme.py),
  [statistics persistence](./marketdata/collectors/statistics.py),
  [manual public report import](./marketdata/management/commands/import_public_report.py),
  [source format tests](./marketdata/tests/test_source_formats.py).
- Preliminary/final riêng, 5 verified CBOT headings, contract month giữ metadata,
  đối chiếu contract totals; raw PDF không nhận diện được vào quarantine.
- Tests đạt cho text excerpt CORN và quarantine; **live PDF ingestion chưa đạt**.
- Real/production rows nhập: 0 (unit rows không tính).
- Tiếp theo: có PDF gốc tải được để validate extraction và mở rộng sections/exchanges.

### STEP 6 — Eurex và Cboe

- Files: [Eurex](./marketdata/collectors/eurex.py),
  [Cboe](./marketdata/collectors/cboe.py), [registry](./marketdata/collectors/registry.py),
  [source checker](./marketdata/management/commands/check_data_sources.py).
- Cboe thực tế: 12 aggregates, totals khớp. Chưa price/contract/historical series.
- Eurex: GraphQL client/config/pagination/reference persistence; live endpoint trả 404.
- Tests: Cboe actual HTML parser + manual import idempotency đạt.
- Real acceptance rows: Cboe 12; Eurex 0. Production 0.
- Tiếp theo: xác minh lại endpoint/schema Eurex và contract-detail Cboe.

### STEP 7 — CSV imports

- Files: [CSV pipeline](./marketdata/collectors/csv_import.py),
  [Dukascopy](./marketdata/collectors/dukascopy.py),
  [FirstRate](./marketdata/collectors/firstrate.py),
  [import command](./marketdata/management/commands/import_market_csv.py),
  [manifest examples](./docs/).
- Tests: timezone/DST, OHLC bounds, bad-row quarantine, sample/license requirements,
  ZIP member selection bằng actual FirstRate sample.
- Real acceptance import: FirstRate 16.232 bars, 0 rejected, rerun 0 writes.
- Dukascopy chỉ unit/integration; chưa file thật, không AWS requester-pays.
- Production 0. Tiếp theo: cung cấp export Dukascopy có quyền dùng để certify.

### STEP 8 — Data Quality

- Files: [engine](./marketdata/quality.py),
  [quality command](./marketdata/management/commands/check_data_quality.py),
  quarantine/runtime models và regression tests.
- Schema/value/duplicate identity/mapping/gap/staleness/revision/lag rules.
  Missing values không nội suy; import mapping mang user_declared.
- Actual replay scan: 997 WARNING; repeat tạo 0 issue mới.
- Tối ưu scan về batch issue writes và chỉ đọc các cột cần thiết; repeat đo 1,516 giây
  trên acceptance DB trước thêm index 0004, không phải benchmark PostgreSQL.
- Market rows tạo bởi scan: 0.
- Giới hạn: không certify holiday/session calendar hoặc lịch sử thiếu trước record đầu tiên.

### STEP 9 — REST API

- Files: [views](./marketdata/views.py), [API URLs](./marketdata/urls.py),
  [config URLs](./config/urls.py), [OpenAPI](./openapi.yaml),
  [API/export tests](./marketdata/tests/test_import_export_api.py).
- Auth, staff actions, filter/date validation, pagination, DB health, source publication
  timestamp, overview, CSV/Parquet export; jobs URL mới và alias cũ cùng tồn tại.
- Automated tests và API trên replay dataset đạt; không ghi market rows mới.
- Tiếp theo: kiểm thử query plans và connection behavior trên PostgreSQL.

### STEP 10 — Dashboard

- Files: [dashboard view/actions](./marketdata/dashboard.py),
  [template](./marketdata/templates/marketdata/dashboard.html).
- Overview, staff source controls, queue sync/backfill/cancel, committed counts,
  error logs, explorer previews, quality/coverage và export.
- Auth/render test đạt; browser snapshot từ database 86.132 record thật.
- Không sinh progress % hoặc success giả. CSV sources hiển thị nhưng không cho queue
  remote sync; importer vẫn dùng command/manifest.
- Market rows tạo từ dashboard: 0. Chưa kiểm thử đầy đủ mọi tương tác UI qua HTTP live server.

### STEP 11 — Scheduler và performance

- Files: [jobs](./marketdata/jobs.py),
  [worker](./marketdata/management/commands/run_collectors.py),
  [source config](./marketdata/management/commands/configure_source.py),
  [recovery](./marketdata/management/commands/recover_collector.py),
  [PowerShell runner](./scripts/run_collectors.ps1),
  [migration 0004](./marketdata/migrations/0004_operations_indexes.py),
  [export engine](./marketdata/exports.py),
  [export command](./marketdata/management/commands/export_market_data.py),
  [VS Code tasks](./.vscode/tasks.json).
- DB queue/mutex/conditional claim, safe cancellation, retry/backoff, explicit recovery.
  retry_count là HTTP retries; attempt_number là automatic job retry.
- Bulk COT/OHLCV, file transactions, disk-spilled downloads, streamed CSV parsing,
  indexes và bounded Parquet batches.
- Automated queue/lock/cancel/scheduler tests đạt. Chưa PostgreSQL multi-process load test.
- Không cài scheduler thứ hai hoặc Celery/Redis; Windows task chưa tự đăng ký.
- Market rows mới: 0. Tiếp theo: đúng một Windows Task Scheduler entry sau khi PG hoạt động.

### STEP 12 — Nghiệm thu và vận hành

- Files: báo cáo này, [live report](./LIVE_SOURCE_REPORT.md), [README Windows](./README.md),
  [runbook](./docs/OPERATIONS.md), [.env example](./.env.example),
  [requirements](./requirements.txt), [.gitignore](./.gitignore),
  [evidence scripts](./scripts/).
- Checks: 74 tests; local/deploy checks; migration drift; OpenAPI validation; real-source
  replay, repeat import, quality scan, exports và dashboard snapshot.
- Real acceptance records: **86.132**. Production records nhập: **0**.
- Không đánh dấu production PASS khi PostgreSQL/CME/Eurex còn các giới hạn trên.

## Điều kiện còn lại để nghiệm thu production

1. PostgreSQL connection hợp lệ, migrate và chạy suite bằng PostgreSQL.
2. Replay/real sync trên PG; kiểm chứng concurrent workers, cancel và database outage thật.
3. CME PDF gốc + end-to-end extraction; mở rộng CME/CBOT/NYMEX/COMEX theo định dạng đã xác minh.
4. Eurex endpoint/schema hoạt động; configured query thực và persistence live.
5. Cboe contract detail/history nếu vẫn nằm trong phạm vi public.
6. File Dukascopy thật và đối chiếu 994 historical-gap warnings theo lịch phát hành.
7. Kiểm thử đầy đủ dashboard controls qua live server và benchmark PostgreSQL.

Không có hành động phá hủy dữ liệu, thay đổi license hoặc truy cập có phí được thực hiện.

