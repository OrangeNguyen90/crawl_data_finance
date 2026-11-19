import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector, archive_details
from marketdata.collectors.cme import CmeCollector
from marketdata.collectors.cboe import CboeCollector
from marketdata.models import DataSource, RawDataFile, FuturesDailyStatistic

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*2025.csv")), ids=lambda p: p.name)
def test_all_six_actual_cftc_schemas(path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.txt", path.read_bytes())
    details = archive_details(path.with_suffix(".zip").name)
    rows = [CftcCollector().normalize(r, *details[1:]) for r in CftcCollector().parse(stream.getvalue())]
    assert len(rows) == 2
    assert rows[0]["report_type"] == details[1] and rows[0]["futures_options_scope"] == details[2]
    assert rows[0]["trader_positions"]


def test_cboe_actual_html_and_reconciled_totals():
    rows = list(CboeCollector().parse((FIXTURES / "cboe_summary.html").read_bytes()))
    assert len(rows) == 12
    assert sum(r["volume"] for r in rows) == 213393
    assert sum(r["open_interest"] for r in rows) == 391482
    assert all(r["contract_type"] == "product_aggregate" for r in rows)


def test_cme_official_text_excerpt_totals():
    rows = list(CmeCollector().parse_text((FIXTURES / "cme_pg03_excerpt.txt").read_text(encoding="utf-8-sig")))
    assert len(rows) == 13
    assert sum(r["volume"] for r in rows) == 464534
    assert rows[0]["open_interest"] == 736488
    assert rows[0]["change_in_oi"] == -21557
    assert rows[0]["metadata"]["contract_month"] == "2026-12"
    assert rows[0]["report_status"] == "preliminary"


def test_cme_mismatched_totals_rejected():
    text = (FIXTURES / "cme_pg03_excerpt.txt").read_text(encoding="utf-8-sig")
    with pytest.raises(CollectorError, match="reconcile"):
        list(CmeCollector().parse_text(text.replace("TOTAL CORN FUT 15047", "TOTAL CORN FUT 15048")))


def test_cme_pdf_not_recognized():
    with pytest.raises(CollectorError):
        list(CmeCollector().parse(b"not a pdf"))


@pytest.mark.django_db
def test_preliminary_never_overwrites_final():
    source = DataSource.objects.create(name="cme", provider_type="daily_statistics")
    raw = RawDataFile.objects.create(source=source, sha256="c" * 64, file_name="test.pdf", file_size=1, file_format="pdf")
    collector = CmeCollector()
    row = next(collector.parse_text((FIXTURES / "cme_pg03_excerpt.txt").read_text(encoding="utf-8-sig")))
    final = {**row, "report_status": "final", "open_interest": 999}
    collector.persist([final], raw)
    collector.persist([row], raw)
    assert FuturesDailyStatistic.objects.get(report_status="final").open_interest == 999
    assert FuturesDailyStatistic.objects.count() == 2

