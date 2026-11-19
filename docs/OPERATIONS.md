# Vận hành và khôi phục

## Quy tắc dữ liệu

- Transaction theo file/page: accepted rows và checkpoint cùng commit.
- Record không hợp lệ không ghi đè dữ liệu đã có; giữ payload trong quarantine.
- Lỗi schema/ZIP hoặc database rollback toàn file, giữ raw để replay.
- Nếu database mất hoàn toàn, không thể ghi trạng thái job vào chính database đó.
  JSON log báo job_state_write_failed/lock_release_failed; khi database phục hồi,
  phải đối chiếu worker thực tế và khôi phục bookkeeping thủ công.
- records_downloaded hiện đếm **files**, không phải số dòng.
- Source revision giữ raw cũ; CotReport trỏ raw mới và issue INFO lưu old/new raw ID.
- CFTC incremental tải lại archive để tính SHA; không parse/upsert khi SHA và phạm vi
  checkpoint không đổi. Đây là weekly refresh qua annual archives, chưa dùng file weekly riêng.
- Publication date/time chỉ lưu khi nguồn cung cấp; không suy diễn ngày công bố từ thứ Ba.

## Job lỗi

1. Xem CollectorJob và DataQualityIssue trong dashboard/admin, ghi lại source/job ID.
2. Kiểm tra raw processing_status và SHA; không sửa bytes gốc.
3. Với lỗi HTTP 403/404, dừng ở lỗi nguồn; không bypass access control hoặc chuyển sang DataShop.
4. Với row lỗi, xem QuarantinedRecord; kiểm tra schema và sửa parser/manifest rồi rerun.
   Checkpoint chỉ ghi khi file không còn row bị từ chối.
5. Với database lỗi, phục hồi connection trước. Không tạo scheduler mới để “sửa” worker.

## Worker chết và lock cũ

Xác minh và dừng đúng process worker trước khi release lock. Không dựa riêng vào tuổi
heartbeat để kết luận process đã chết.

~~~powershell
.\.venv\Scripts\python.exe manage.py recover_collector --source cftc --worker-stopped --owner OWNER_UUID
~~~

Nếu worker chết giữa claim và tạo lock, dùng --job-id JOB_ID thay --owner.
Command chỉ khôi phục claimed orphan của đúng nguồn khi không có source lock.
Không xóa market records; raw đang processing được chuyển failed.
Rerun lệnh gốc hoặc enqueue job mới; các checkpoint đã commit sẽ được tái sử dụng.

## Duplicate instruments khi migrate

Migration 0003 kiểm tra duplicate (exchange, symbol) với expiration=NULL trước khi
tạo conditional unique constraint. Nếu bị chặn:

1. Dừng collectors của nguồn liên quan.
2. Lập danh sách ID và toàn bộ FK references (bars/statistics/mappings/quality).
3. Xác minh hai ID thực sự cùng instrument và phạm vi hợp đồng.
4. Chỉ chuẩn bị migration gộp sau khi có quyết định cụ thể của người vận hành.

Không tự xóa hoặc gộp dữ liệu. Migration hiện tại không thực hiện bước phá hủy nào.

## Quality warnings

Trong replay 2025, 994 historical_gap warnings phản ánh khoảng cách giữa các report
dates đã quan sát; chưa kết luận đó là thiếu sót nguồn. Lịch phát hành, đình chỉ phát
hành, thay đổi market coverage cần được đối chiếu thủ công. Scan không tạo record
thay thế, không nội suy giá/OI. Scan chưa certify lịch phiên intraday/holiday calendar.

unverified_mapping của CSV import cần xác minh bằng identifier/specification thực.
Không đổi trạng thái chỉ vì tên hàng hóa giống nhau. CFE product aggregates không
phải từng hợp đồng đáo hạn. Source stale và observation stale là hai tín hiệu khác nhau.

## Sao lưu và bảo mật

Sao lưu PostgreSQL bằng công cụ quản trị hiện có và bảo vệ thư mục raw_data;
không đưa dump, .env, .venv, sample raw hoặc credentials vào Git.
Thư mục này ban đầu chưa có .git; chưa tạo repository/commit tự động.

Staff có quyền điều khiển collector; người đọc API chỉ được đọc dữ liệu trong phạm vi
license. Bật HTTPS khi ra ngoài localhost. Không đưa password vào URL hoặc command
arguments. Probe database chỉ in backend và exception class, không in connection string.

Không thay đổi PostgreSQL authentication hoặc PostgreSQL service để vượt qua lỗi
kết nối. Không truy cập AWS requester-pays Dukascopy hoặc sản phẩm dữ liệu trả phí.

