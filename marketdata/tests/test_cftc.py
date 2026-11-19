import io
import zipfile
from datetime import date

import pytest

from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector, archive_details
from marketdata.models import CotReport, DataSource, RawDataFile


def sample_zip(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sample.txt", text)
    return stream.getvalue()


HEADER = "Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,CFTC_Contract_Market_Code,Open_Interest_All,M_Money_Positions_Long_All\n"
ROW = "TEST MARKET,250107,123456,1000,250\n"


def test_archive_types_are_separate():
    assert archive_details("https://www.cftc.gov/files/dea/history/fut_disagg_txt_2025.zip") == (2025, "disaggregated", "futures_only")
    assert archive_details("https://www.cftc.gov/files/dea/history/com_disagg_txt_2025.zip") == (2025, "disaggregated", "combined")
    assert archive_details("https://www.cftc.gov/files/dea/history/deacot2025.zip") == (2025, "legacy", "futures_only")


def test_parser_and_normalizer():
    collector = CftcCollector()
    row = next(collector.parse(sample_zip(HEADER + ROW)))
    normalized = collector.normalize(row, "disaggregated", "futures_only")
    assert normalized["report_date"] == date(2025, 1, 7)
    assert normalized["open_interest"] == 1000
    assert normalized["trader_positions"]["m_money_positions_long_all"] == 250


def test_invalid_zip_and_missing_columns():
    collector = CftcCollector()
    with pytest.raises(CollectorError, match="ZIP"):
        list(collector.parse(b"not a zip"))
    with pytest.raises(CollectorError, match="Missing"):
        collector.normalize({"market_and_exchange_names": "x"}, "legacy", "combined")


def test_url_restriction():
    collector = CftcCollector()
    for url in ("http://www.cftc.gov/a", "https://127.0.0.1/a", "https://www.cftc.gov.evil.test/a"):
        with pytest.raises(CollectorError):
            collector._check_url(url)


@pytest.mark.django_db
def test_persist_is_idempotent_and_preserves_scope():
    source = DataSource.objects.create(name="cftc", provider_type="cot", official_url="https://www.cftc.gov")
    raw = RawDataFile.objects.create(source=source, file_name="x.zip", original_url="https://www.cftc.gov/x.zip",
        file_format="zip", sha256="a" * 64, file_size=1, storage_path="x")
    collector = CftcCollector()
    row = collector.normalize(next(collector.parse(sample_zip(HEADER + ROW))), "disaggregated", "futures_only")
    assert collector.persist([row], raw) == (1, 0, 0)
    assert collector.persist([row], raw) == (0, 1, 0)
    assert CotReport.objects.count() == 1
    combined = {**row, "futures_options_scope": "combined"}
    assert collector.persist([combined], raw) == (1, 0, 0)
    assert CotReport.objects.count() == 2
