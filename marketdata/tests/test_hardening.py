import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from rest_framework.test import APIClient

from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector
from marketdata.models import CollectorCheckpoint, CollectorJob, CotReport, DataQualityIssue, DataSource, RawDataFile
from marketdata.quality import scan_quality
from marketdata.exports import csv_chunks, write_parquet

HEADER = "Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,CFTC_Contract_Market_Code,Open_Interest_All,NonComm_Positions_Long_All\n"
URL = "https://www.cftc.gov/files/dea/history/deacot2025.zip"


def zipped(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.csv", text.encode("cp1252"))
    return output.getvalue()


@pytest.fixture
def c(db, settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path
    DataSource.objects.create(name="cftc", enabled=True, provider_type="cot", data_frequency="weekly")
    collector = CftcCollector()
    collector.discover = lambda: [URL]
    return collector


def test_cp1252_encoding_and_official_special_values():
    row = next(CftcCollector().parse(zipped(HEADER + "Cafe é,250107,12460+,-0,0\n")))
    normalized = CftcCollector().normalize(row, "legacy", "futures_only")
    assert normalized["market_name"] == "Cafe é"
    assert normalized["market_code"] == "12460+" and normalized["open_interest"] == 0
    assert normalized["raw_fields"]["open_interest_all"] == "-0"


def test_duplicate_normalized_headers_rejected():
    with pytest.raises(CollectorError, match="Duplicate"):
        list(CftcCollector().parse(zipped("A,A\n1,2\n")))


def test_compression_bomb_rejected():
    with pytest.raises(CollectorError, match="compression"):
        list(CftcCollector().parse(zipped("a" * 1000000)))


def test_report_family_scope_and_date_consistency():
    collector = CftcCollector()
    row = next(collector.parse(zipped(HEADER + "TEST,250107,123456,100,50\n")))
    with pytest.raises(CollectorError, match="family"):
        collector.normalize(row, "tff", "futures_only")
    row["futonly_or_combined"] = "Combined"
    with pytest.raises(CollectorError, match="scope"):
        collector.normalize(row, "legacy", "futures_only")
    row.pop("futonly_or_combined")
    row["report_date_as_yyyy_mm_dd"] = "2025-01-08"
    with pytest.raises(CollectorError, match="disagree"):
        collector.normalize(row, "legacy", "futures_only")


def test_invalid_revision_does_not_overwrite_verified_row(c):
    c.download = lambda url: zipped(HEADER + "TEST,250107,123456,100,50\n")
    c.backfill(date(2025, 1, 1), date(2025, 12, 31))
    original_file = CotReport.objects.get().source_file_id
    c.download = lambda url: zipped(HEADER + "TEST,250107,123456,-10,50\n")
    job = c.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert job.status == "partial"
    assert CotReport.objects.get().open_interest == 100
    assert CotReport.objects.get().source_file_id == original_file


def test_sync_checkpoint_independent_of_day(c):
    c.download = lambda url: zipped(HEADER + "TEST,250107,123456,100,50\n")
    with patch("marketdata.collectors.cftc.timezone.now", return_value=datetime(2026, 1, 5, tzinfo=timezone.utc)):
        assert c.sync().records_inserted == 1
    with patch("marketdata.collectors.cftc.timezone.now", return_value=datetime(2026, 1, 6, tzinfo=timezone.utc)):
        job = c.sync()
    assert job.records_inserted == job.records_updated == 0


def test_failure_after_committed_batch_rolls_back_entire_file(c):
    rows = "".join(f"TEST,250107,{number:06d},100,50\n" for number in range(501))
    c.download = lambda url: zipped(HEADER + rows)
    original = CotReport.objects.bulk_create
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OperationalError("private")
        return original(*args, **kwargs)
    with patch.object(CotReport.objects, "bulk_create", side_effect=fail_second), pytest.raises(OperationalError):
        c.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert calls == 2
    assert CotReport.objects.count() == 0 and CollectorCheckpoint.objects.count() == 0
    assert RawDataFile.objects.get().processing_status == "failed"


def test_download_failure_is_visible_as_failed_job(c):
    with patch.object(c, "download", side_effect=CollectorError("Source HTTP 403")), pytest.raises(CollectorError):
        c.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert CollectorJob.objects.get().status == "failed"


def test_quality_scan_is_repeatable(c):
    assert scan_quality() >= 1
    count = DataQualityIssue.objects.count()
    assert scan_quality() == 0 and DataQualityIssue.objects.count() == count


def test_schema_and_docs_require_auth():
    assert APIClient().get("/api/schema/").status_code in (401, 403)
    assert APIClient().get("/api/docs/").status_code in (401, 403)


@pytest.mark.django_db
def test_cboe_local_report_command_is_idempotent(settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path
    DataSource.objects.create(name="cboe", enabled=True, provider_type="daily_statistics")
    file = Path(__file__).parent / "fixtures/cboe_summary.html"
    args = {"source": "cboe", "file": str(file), "official_url": "https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/"}
    call_command("import_public_report", **args, stdout=io.StringIO())
    call_command("import_public_report", **args, stdout=io.StringIO())
    from marketdata.models import FuturesDailyStatistic
    assert FuturesDailyStatistic.objects.count() == 12
    assert CollectorJob.objects.latest("id").records_inserted == 0


@pytest.mark.django_db
def test_unrecognized_pdf_retained_in_quarantine(settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path / "raw"
    DataSource.objects.create(name="cme", enabled=True, provider_type="daily_statistics")
    file = tmp_path / "unsupported.pdf"
    file.write_bytes(b"invalid pdf original evidence")
    with pytest.raises(CommandError):
        call_command("import_public_report", source="cme", file=str(file),
            official_url="https://www.cmegroup.com/daily_bulletin/current/Section03_Agricultural_Futures.pdf")
    raw = RawDataFile.objects.get()
    assert raw.processing_status == "quarantined"
    assert Path(raw.storage_path).read_bytes() == file.read_bytes()
    assert CollectorJob.objects.get().status == "failed"

