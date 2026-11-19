# Live Source Tests — 2026-11-04

## Phương pháp và giới hạn chứng cứ

Network probe dùng Requests trên máy Windows, timeout/size limit/retry có giới hạn,
không follow redirect hoặc bypass access control. Raw tải được lưu trong thư mục
local ignored. Sau khi sửa parser, kiểm chứng lại toàn bộ bytes đã tải và replay vào
database nghiệm thu SQLite **mới, tách biệt**. Không có production PostgreSQL import.

Kết quả network download, parse cached raw, unit fixture và persistence replay được
phân biệt dưới đây. Không coi mock hoặc text excerpt là live ingestion.

## CFTC

Discovery từ [official historical index](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm).
Sáu archive 2025 được khám phá từ link thật; không tự ghép URL để discovery.
Replay chỉ dùng chính những archive đã tải đó.

| Archive | Rows parse/normalize | Rows nhập vào acceptance DB | Rejected |
|---|---:|---:|---:|
| com_disagg_txt_2025.zip | 13.941 | 13.941 | 0 |
| com_fin_txt_2025.zip | 3.687 | 3.687 | 0 |
| deacot2025.zip | 17.316 | 17.316 | 0 |
| deahistfo2025.zip | 17.628 | 17.628 | 0 |
| fut_disagg_txt_2025.zip | 13.630 | 13.630 | 0 |
| fut_fin_txt_2025.zip | 3.686 | 3.686 | 0 |
| **Tổng** | **69.888** | **69.888** | **0** |

Chạy lại cả sáu phạm vi: inserted=0, updated=0; số record vẫn 69.888.
Đã xử lý hai biến thể header Legacy/spaces và các biến thể Disaggregated/TFF.
Dữ liệu thật có mã 12460+ và số -0: parser giữ raw_fields nguyên chuỗi, số chuẩn hóa 0.

Kết quả đầu tiên của probe có parse failures trước khi sửa validator. Không dùng
các trạng thái parse cũ đó làm kết quả cuối; full validation/replay sau sửa đều đạt.
Chưa certify archive mọi năm từ 1986 hoặc weekly transport riêng; incremental hiện
refresh annual archives của năm hiện tại/năm trước và so SHA trước khi parse.

## Cboe

Requests tải thành công HTML của
[Daily Futures Statistics](https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/).
Đã parse 12 dòng product aggregate cho 2026-11-03 và đối chiếu:
Volume=213.393, Open Interest=391.482.

Nhập 12 dòng vào acceptance DB; chạy persist lần hai vẫn 12, không tạo trùng.
Cột report_status là unspecified vì bảng không công bố nhãn Preliminary/Final.
Không suy diễn giá, contract month hoặc expiration từ bảng tổng hợp.
Chưa chứng nhận product detail prices, từng hợp đồng hoặc historical backfill.
Không truy cập sản phẩm DataShop trả phí.

## CME

[Official bulletin](https://www.cmegroup.com/market-data/daily-bulletin.html) và
[PG03 PDF](https://www.cmegroup.com/daily_bulletin/current/Section03_Agricultural_Futures.pdf)
được xác minh qua web reader. Local Requests không tải thành công trang/PDF trong
phiên probe. Không có PDF gốc local để chứng nhận pypdf extraction.

Text parser được kiểm thử bằng excerpt CORN thật của 2026-11-03:
13 contracts, Volume=464.534, OI=1.918.566, OI change=+8.155, Preliminary.
Đây là **text-fixture validation**, không phải live PDF import PASS.

Adapter chỉ cho phép năm heading CBOT đã xác minh. Các sản phẩm/section khác và
CME/NYMEX/COMEX chưa được chứng nhận. Khi có PDF local hợp lệ có thể chạy
import_public_report; file không nhận diện được phải quarantine và giữ nguyên bytes.
Production CME rows nhập trong phiên này: 0.

## Eurex

[Official API documentation](https://www.eurex.com/ex-en/data/free-reference-data-api)
được tải thật. Một request GraphQL introspection đến endpoint được tài liệu chỉ ra,
dùng public shared key công bố tại trang, trả **HTTP 404**. Key không in ra log và
không lưu vào repository; script hiện chỉ đọc EUREX_API_KEY từ environment.

Trạng thái: LIMITED. Không có product/contract reference rows nhập thành công.
Client/pagination/configured persistence có mã triển khai, nhưng chưa có schema/default
query được xác minh live. Chỉ cấu hình EUREX_QUERY_FILE sau khi endpoint/schema hoạt động.
Không tạo OHLCV từ reference data.

## FirstRate

Public ES sample được liên kết trực tiếp trên
[official product page](https://firstratedata.com/i/futures/ES), download trả HTTP 200.
Đọc sample README và [license](https://firstratedata.com/about/license) trước khi
đánh giá riêng tư. Không thay đổi license và không phân phối raw sample trong repo.

Nhập member ES_1min_sample.csv từ ZIP:
- 16.232 bars, từ 2026-10-19 đến 2026-11-03 theo America/New_York.
- SAMPLE=true; trade volume; nguồn, license URL và date range được lưu.
- Adjustment method ghi unspecified_by_sample_filename, không tự đoán.
- Rejected=0; import lại inserted=updated=0.
- Không đại diện toàn lịch sử ES; symbol sample riêng với contract_type continuous_future.

## Dukascopy

Manual CSV/ZIP importer được unit/integration-test về schema, OHLC, bid/ask,
timezone/DST và FX-spot namespace. **Chưa có file export thật** để certify live import.

Tài liệu [historical bulk export](https://www.dukascopy.com/wiki/en/development/data-export/)
hiện mô tả AWS requester-pays. Không truy cập đường trả phí, không dùng credentials AWS,
không coi dữ liệu test tự tạo là live data.

## Persistence, API, dashboard, export

Acceptance DB có 86.132 observations thật: 69.888 COT + 12 CFE aggregates +
16.232 FirstRate sample bars. CSV và Parquet COT đều 69.888 rows;
Parquet giữ trader_positions dưới dạng JSON cùng schema Decimal/date/UTC phù hợp.

API health kiểm tra SELECT 1 trong acceptance DB đạt; malformed date trả 400.
Dashboard đã render và kiểm tra bằng browser snapshot từ database này.
Không coi health của SQLite là PostgreSQL readiness.

Quality scan tạo 997 WARNING: 994 historical_gap, 1 stale_observation,
1 stale_source, 1 user_declared mapping. Scan lại tạo 0 warning mới.
Chưa kết luận nguyên nhân 994 gaps; không tự điền record. Không có ERROR/CRITICAL
được phát hiện trong replay dataset bằng các rule đã triển khai.

## PostgreSQL

Ban đầu connection thất bại vì database cấu hình chưa tồn tại. Đã tạo database,
áp dụng migrations đến 0004 và kiểm chứng probe PostgreSQL PASS, Django check PASS.
Bộ **74 tests passed trên PostgreSQL**, sử dụng một database test UUID riêng.
Database test do lần chạy này tạo được framework thu dọn sau tests.
Chưa import market observations vào PostgreSQL vận hành; số production rows nhập: **0**.

Evidence local có raw archives, sample ZIP, results.json, acceptance.json và HTML
preview trong live_evidence. Các file này không thay thế báo cáo production certification.

