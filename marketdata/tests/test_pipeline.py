import io
import zipfile
from datetime import date
from unittest.mock import patch

import pytest
from django.db import OperationalError

from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector
from marketdata.models import CollectorJob, CotReport, DataSource, RawDataFile

HEADER = "Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,CFTC_Contract_Market_Code,Open_Interest_All,NonComm_Positions_Long_All\n"
URL = "https://www.cftc.gov/files/dea/history/deacot2025.zip"


def archive(text):
    handle = io.BytesIO()
    with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.txt", text.encode("cp1252"))
    return handle.getvalue()


@pytest.fixture
def source(db, settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path
    return DataSource.objects.create(name="cftc", provider_type="cot", official_url="https://www.cftc.gov", enabled=True)


@pytest.fixture
def collector(source):
    c = CftcCollector()
    c.discover = lambda: [URL]
    return c


def test_narrow_backfill_does_not_skip_later_range(collector):
    collector.download = lambda url: archive(HEADER + "TEST,250107,123456,100,50\nTEST,250114,123456,110,55\n")
    collector.backfill(date(2025, 1, 7), date(2025, 1, 7))
    collector.backfill(date(2025, 1, 14), date(2025, 1, 14))
    assert CotReport.objects.count() == 2


def test_invalid_row_quarantined_without_aborting_good_rows(collector):
    collector.download = lambda url: archive(HEADER + "TEST,250107,123456,bad,50\nTEST,250114,123456,110,55\n")
    job = collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert (job.status, job.records_rejected, job.records_inserted) == ("partial", 1, 1)


def test_database_failure_rolls_back_file(collector):
    collector.download = lambda url: archive(HEADER + "TEST,250107,123456,100,50\n")
    with patch.object(CotReport.objects, "bulk_create", side_effect=OperationalError("private connection details")):
        with pytest.raises(OperationalError):
            collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert CotReport.objects.count() == 0
    assert CollectorJob.objects.latest("id").status == "failed"
    assert "private" not in CollectorJob.objects.latest("id").error_message


def test_repeated_sync_and_source_revision(collector):
    data = [archive(HEADER + "TEST,250107,123456,100,50\n")]
    collector.download = lambda url: data[0]
    c1 = collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    c2 = collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert (c1.records_inserted, c2.records_inserted, c2.records_updated) == (1, 0, 0)
    data[0] = archive(HEADER + "TEST,250107,123456,120,60\n")
    c3 = collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert c3.records_updated == 1
    assert CotReport.objects.get().open_interest == 120
    assert RawDataFile.objects.count() == 2


def test_disabled_source_is_not_run(collector, source):
    source.enabled = False
    source.save()
    with pytest.raises(CollectorError, match="disabled"):
        collector.sync()


def test_csv_shape_is_not_silently_discarded():
    with pytest.raises(CollectorError):
        list(CftcCollector().parse(archive(HEADER + "TEST,250107,123456,100,50,EXTRA\n")))

