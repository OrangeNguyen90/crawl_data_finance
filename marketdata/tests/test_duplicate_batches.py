import io
import zipfile
from datetime import date

import pytest

from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector
from marketdata.models import CotReport, DataSource

HEADER = "Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,CFTC_Contract_Market_Code,Open_Interest_All,NonComm_Positions_Long_All\n"
URL = "https://www.cftc.gov/files/dea/history/deacot2025.zip"


def zipped(text):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.csv", text)
    return target.getvalue()


@pytest.mark.django_db
def test_conflicting_duplicate_after_batch_boundary_rolls_back(settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path
    DataSource.objects.create(name="cftc", enabled=True, provider_type="cot")
    collector = CftcCollector()
    collector.discover = lambda: [URL]
    text = HEADER + "".join(f"TEST,250107,{n:06d},100,50\n" for n in range(500))
    text += "TEST,250107,000000,999,50\n"
    collector.download = lambda url: zipped(text)
    with pytest.raises(CollectorError, match="Conflicting"):
        collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert CotReport.objects.count() == 0


@pytest.mark.django_db
def test_identical_duplicate_count_is_not_double_reported(settings, tmp_path):
    settings.MARKETDATA_RAW_ROOT = tmp_path
    DataSource.objects.create(name="cftc", enabled=True, provider_type="cot")
    collector = CftcCollector()
    collector.discover = lambda: [URL]
    collector.download = lambda url: zipped(HEADER + "TEST,250107,123456,100,50\n" * 2)
    job = collector.backfill(date(2025, 1, 1), date(2025, 12, 31))
    assert job.records_inserted == 1 and job.records_updated == 0
    assert CotReport.objects.count() == 1

