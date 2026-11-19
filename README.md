# Crawl Data Finance V2.0

Nâng cấp Django repository hiện hữu. PostgreSQL là database vận hành; SQLite chỉ
dùng cho test được bật rõ ràng. Xem [audit](./AUDIT_REPORT.md),
[nghiệm thu](./ACCEPTANCE_REPORT.md) và [kiểm chứng nguồn](./LIVE_SOURCE_REPORT.md).

## Phạm vi hiện tại

| Nguồn | Khả năng | Giới hạn |
|---|---|---|
| CFTC | Discovery chính thức, sáu loại archive, backfill năm/ngày/market, SHA checkpoint, weekly refresh qua annual archive đang cập nhật | Chưa chứng nhận toàn bộ lịch sử từ 1986; 2025 đã replay đủ sáu archive |
| CME | Discovery PG03, lưu PDF, parser nghiêm ngặt cho năm sản phẩm CBOT và đối chiếu totals | Local download chưa thành công; chưa chứng nhận PDF extraction, CME/NYMEX/COMEX hoặc các section khác |
| Cboe | HTML công khai: 12 product aggregates, đối chiếu totals | Chưa có contract detail, prices hoặc historical discovery |
| Eurex | GraphQL client, env key, schema-config query, pagination, reference persistence | Endpoint tài liệu trả 404; chưa có default query được xác minh |
| Dukascopy | Import OHLC CSV/ZIP bid/ask, timezone, quote volume | Chưa kiểm chứng file export thật; không truy cập requester-pays AWS |
| FirstRate | CSV/ZIP SAMPLE, metadata, date range, adjustment label | Sample riêng tư để đánh giá; không đại diện full history |

Không suy diễn OHLCV từ Volume/OI hoặc reference data. Không tự ghép CFTC market code
với hợp đồng CME hay ghép FX spot thành currency futures.

## Chạy trên Windows 10/11

Mở PowerShell tại thư mục dự án, sử dụng venv Python 3.12 hiện có:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PGDATABASE = 'marketdata'
$env:PGUSER = 'postgres'
$env:PGHOST = 'localhost'
$env:PGPORT = '5432'
$pgSecret = Read-Host 'PostgreSQL password' -AsSecureString
$env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $pgSecret).Password
$env:DJANGO_SECRET_KEY = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe scripts/probe_database.py
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate --plan
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py list_data_sources
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
~~~

Không in biến secret ra terminal. Cấu hình môi trường bền vững cho cùng Windows
account khi chạy scheduler; secret trên chỉ tồn tại trong PowerShell hiện tại.
Giữ nguyên DJANGO_SECRET_KEY giữa các lần khởi động để session không mất hiệu lực.
Sao chép [.env.example](./.env.example) thành `.env` và điền cấu hình local.
Settings tự nạp file `.env` (được Git bỏ qua); biến môi trường đã có được ưu tiên.
`DJANGO_DEBUG=1` cho phép `runserver` phục vụ CSS của Django admin khi chạy local.
Khởi động lại server sau khi sửa `.env`. Trong production, đặt `DJANGO_DEBUG=0`
và cấu hình máy chủ web phục vụ static files.
Nếu database cấu hình chưa tồn tại, chạy trước migrations:

~~~powershell
.\.venv\Scripts\python.exe manage.py bootstrap_database
.\.venv\Scripts\python.exe manage.py migrate --noinput
~~~

bootstrap_database kết nối database quản trị postgres để tạo database đích nếu thiếu;
không xóa hoặc tạo lại database đã có. Tài khoản cần quyền CREATEDB.

Dashboard: http://127.0.0.1:8000/ — yêu cầu staff login qua Django admin.
OpenAPI: /api/schema/ và /api/docs/ — yêu cầu authentication.
Swagger UI mặc định tải asset CDN; [OpenAPI YAML](./openapi.yaml) dùng được offline.

Migration 0001 được giữ nguyên. Migration mới thêm runtime/provenance/indexes.
Migration 0003 dừng nếu có instrument không ngày đáo hạn bị trùng, không tự gộp/xóa
record. Đọc [runbook](./docs/OPERATIONS.md) trước khi xử lý trường hợp này.

## Đồng bộ và backfill

~~~powershell
.\.venv\Scripts\python.exe manage.py sync_source --source cftc
.\.venv\Scripts\python.exe manage.py backfill_source --source cftc --year 2025 --report-type disaggregated --scope futures_only
.\.venv\Scripts\python.exe manage.py backfill_source --source cftc --start 2025-01-01 --end 2025-03-31 --market-code 002602
.\.venv\Scripts\python.exe manage.py check_data_sources --source cftc
.\.venv\Scripts\python.exe manage.py check_data_quality
~~~

Nguồn ngoài CFTC mặc định disabled; enable có chủ đích sau khi kiểm tra phạm vi:

~~~powershell
.\.venv\Scripts\python.exe manage.py configure_source --source cboe --enable
.\.venv\Scripts\python.exe manage.py sync_source --source cboe
~~~

Để replay archive đã tải, dùng import_cftc_archive --file FILE --official-url URL.
Để nhập CME PDF/Cboe HTML lưu thủ công, dùng import_public_report --source cme
--file FILE --official-url URL; --published-at chỉ dùng khi có timestamp thực từ nguồn.
Parser không nhận diện được sẽ giữ raw và quarantine, không tạo dữ liệu thành công giả.

## Import CSV/ZIP

Sao chép [Dukascopy manifest](./docs/dukascopy-manifest.example.json) hoặc
[FirstRate manifest](./docs/firstrate-manifest.example.json), điền đúng metadata
của file và chỉ đặt license_status=permitted khi quyền sử dụng đã xác minh.
Ví dụ cố ý để license unverified để không tự cấp quyền.

~~~powershell
.\.venv\Scripts\python.exe manage.py configure_source --source dukascopy --enable
.\.venv\Scripts\python.exe manage.py import_market_csv --source dukascopy --file D:/data/EURUSD.csv --manifest D:/data/eurusd-manifest.json
~~~

Header timestamp/open/high/low/close/volume hoặc Time (UTC)/GMT time/Local time
được hỗ trợ; timezone và timestamp_format phải phù hợp thực tế. Headerless CSV cần
header=false và có thể khai báo columns. ZIP có nhiều CSV cần member chính xác.
Không extract archive ra đường dẫn bên ngoài. FirstRate phải có sample=true,
start/end theo ngày ở timezone nguồn và adjustment_method; unknown phải ghi rõ.
Datetime ở thời điểm DST mơ hồ phải có UTC offset, không tự chọn fold.

Raw bytes được lưu atomically và giữ SHA256; row lỗi vào QuarantinedRecord.
Manifest nằm trong raw metadata, checkpoint và bar.raw_fields. Mapping import do
người dùng khai báo mang trạng thái user_declared cho đến khi được xác minh.

## API và export

API read cần session hoặc Basic authentication; thao tác collector/jobs cần staff.
Dùng TLS khi triển khai ngoài localhost. API không chia sẻ công khai dữ liệu có
giới hạn license. Giữ người dùng FirstRate trong phạm vi quyền sử dụng.

Ví dụ GET: /api/v1/cot/?start=2025-01-01&end=2025-03-31&market_code=002602&report_type=legacy&futures_options_scope=futures_only
OI: /api/v1/open-interest/?source=cboe&exchange=CFE&report_status=unspecified
OHLCV: /api/v1/ohlcv/?symbol=EURUSD&timeframe=1m&price_type=bid
Dates inclusive theo ngày UTC trên API. Ngày sai trả 400. Pagination 100 record/page.
Preliminary và final là hai series riêng; lọc report_status=final khi cần dữ liệu final.

~~~powershell
.\.venv\Scripts\python.exe manage.py export_market_data --dataset cot --file-format parquet --output exports/cot-2025.parquet --start 2025-01-01 --end 2025-12-31
~~~

Các dataset: cot, open-interest, ohlcv, instruments. CSV streaming, Parquet batch
2.000 rows, giữ Decimal/UTC và JSON positions/metadata. raw_fields lớn vẫn ở API
và raw archive; không đưa mặc định vào export. File output tồn tại sẽ bị từ chối.

## Scheduler nhẹ

~~~powershell
.\.venv\Scripts\python.exe manage.py configure_source --source cftc --interval-minutes 1440 --max-retries 2
.\.venv\Scripts\python.exe manage.py run_collectors --schedule --retry-failed --max-jobs 4
~~~

Tạo đúng **một** Windows Task Scheduler task, trigger mỗi 5 phút, action:
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File
E:\Project\crawl_data_finance\scripts\run_collectors.ps1
Chọn “Do not start a new instance”. Start in là thư mục repository; dùng đúng
Windows account có biến môi trường database. Không cài Celery/Redis.

Mỗi nguồn có một DB mutex. Hàng đợi bền vững; job được claim bằng conditional update.
Stop chỉ yêu cầu hủy ở checkpoint an toàn. Retry có giới hạn và giữ parameters.
Xem runbook để khôi phục lock/claim khi worker chết; không tự hết hạn một worker
có thể vẫn còn hoạt động.

## Tests và nghiệm thu

~~~powershell
$env:MARKETDATA_SQLITE_TEST = '1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py spectacular --validate --file openapi.yaml
Remove-Item Env:MARKETDATA_SQLITE_TEST
~~~

Để kiểm thử PostgreSQL: cấu hình connection của test account có quyền tạo test DB,
không bật MARKETDATA_SQLITE_TEST, rồi chạy pytest. Bộ 74 tests đã được kiểm chứng
trên PostgreSQL bằng database test UUID riêng sau khi khởi tạo database dự án.

Live network probe: scripts/live_probe.py. Cached validation: scripts/validate_evidence.py.
Real-source replay: scripts/acceptance_replay.py tạo **database mới trong temp**,
không sửa database hiện có. FirstRate: scripts/download_sample.py rồi
scripts/acceptance_sample.py. Kết quả raw/JSON trong live_evidence được ignore.
Không tự chạy lại generator fixtures khi nguồn đã chuyển sang ngày khác.

Production: đặt DJANGO_ENV=production, secret ổn định, DEBUG=0, ALLOWED_HOSTS đúng,
HTTPS và WSGI server phù hợp Windows. runserver chỉ dành cho phát triển.
SQLite test backend bị cấm trong production mode.

