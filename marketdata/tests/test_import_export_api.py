import io
import json
from datetime import date, datetime, timezone
from unittest.mock import patch

import pyarrow.parquet as pq
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from marketdata.collectors.base import CollectorError
from marketdata.collectors.csv_import import utc_timestamp
from marketdata.collectors.dukascopy import DukascopyCollector
from marketdata.collectors.firstrate import FirstRateCollector
from marketdata.models import DataSource, Instrument, OhlcvBar, QuarantinedRecord
from marketdata.exports import csv_chunks, write_parquet


@pytest.fixture
def manifest():
    return {"symbol": "EURUSD", "exchange": "DUKASCOPY_FX", "asset_class": "fx_spot",
            "timeframe": "1m", "timezone": "Europe/Berlin", "price_type": "bid", "volume_type": "quote",
            "source_url": "https://www.dukascopy.com/swiss/english/marketwatch/historical/",
            "license_status": "permitted"}


@pytest.fixture
def imported(db, tmp_path, settings, manifest):
    settings.MARKETDATA_RAW_ROOT = tmp_path / "raw"
    DataSource.objects.create(name="dukascopy", provider_type="fx_prices", enabled=True)
    path = tmp_path / "prices.csv"
    path.write_text("timestamp,open,high,low,close,volume\n2025-01-07 10:00:00,1.01,1.03,1.00,1.02,12.5\n", encoding="utf-8")
    job = DukascopyCollector().import_file(path, manifest)
    return path, job


def test_csv_import_timezone_and_repeat(imported, manifest):
    path, job = imported
    assert (job.status, job.records_inserted) == ("success", 1)
    bar = OhlcvBar.objects.get()
    assert bar.timestamp_utc == datetime(2025, 1, 7, 9, tzinfo=timezone.utc)
    assert bar.volume_type == "quote"
    assert bar.instrument.contract_type == "fx_spot"
    repeat = DukascopyCollector().import_file(path, manifest)
    assert repeat.records_inserted == repeat.records_updated == 0
    assert OhlcvBar.objects.count() == 1


@pytest.mark.parametrize("stamp", ["2025-03-30 02:30:00", "2025-10-26 02:30:00"])
def test_ambiguous_and_nonexistent_dst_are_rejected(stamp):
    with pytest.raises(CollectorError):
        utc_timestamp(stamp, "Europe/Berlin")


def test_explicit_offset_resolves_dst():
    assert utc_timestamp("2025-10-26T02:30:00+02:00", "Europe/Berlin").hour == 0


def test_bad_ohlc_is_quarantined(imported, manifest):
    path, _ = imported
    path.write_text("timestamp,open,high,low,close,volume\n2025-01-08 10:00:00,2,1,0,2,10\n", encoding="utf-8")
    job = DukascopyCollector().import_file(path, manifest)
    assert job.status == "partial"
    assert job.records_rejected == 1
    assert QuarantinedRecord.objects.count() == 1
    assert OhlcvBar.objects.count() == 1


@pytest.mark.parametrize("field,value", [("exchange", "CME"), ("asset_class", "future"), ("price_type", "trade"), ("license_status", "unknown")])
def test_manifest_prevents_wrong_semantics(manifest, field, value):
    manifest[field] = value
    with pytest.raises(CollectorError):
        DukascopyCollector().validate_manifest(manifest)


def test_firstrate_requires_sample_and_license(manifest):
    manifest.update(source_url="https://firstratedata.com/", exchange="SAMPLE", price_type="trade", volume_type="trade")
    with pytest.raises(CollectorError, match="SAMPLE"):
        FirstRateCollector().validate_manifest(manifest)


def test_parquet_preserves_decimal_and_utc(imported):
    target = io.BytesIO()
    write_parquet(OhlcvBar.objects.order_by("id"), target)
    target.seek(0)
    row = pq.read_table(target).to_pylist()[0]
    assert str(row["open"]) == "1.01000000"
    assert row["timestamp_utc"].hour == 9
    assert row["volume_type"] == "quote"


def test_empty_parquet_has_schema(db):
    target = io.BytesIO()
    write_parquet(OhlcvBar.objects.all(), target)
    target.seek(0)
    table = pq.read_table(target)
    assert table.num_rows == 0 and "timestamp_utc" in table.schema.names


def test_csv_formula_injection_is_escaped(db):
    Instrument.objects.create(exchange="TEST", symbol="=1+1", instrument_name="@SUM(A1)")
    text = "".join(csv_chunks(Instrument.objects.all()))
    assert "'=1+1" in text and "'@SUM(A1)" in text


@pytest.fixture
def api(db):
    user = get_user_model().objects.create_user(username="reader")
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_api_requires_authentication():
    assert APIClient().get("/api/v1/sources/").status_code in (401, 403)


@pytest.mark.parametrize("url", ["/api/v1/cot/?start=nonsense", "/api/v1/cot/?start=2025-02-01&end=2025-01-01",
    "/api/v1/ohlcv/?instrument=oops", "/api/v1/cot/?report_type=unknown"])
def test_bad_filters_return_400(api, url):
    assert api.get(url).status_code == 400


def test_api_filter_and_pagination(api, imported):
    response = api.get("/api/v1/ohlcv/?start=2025-01-07&end=2025-01-07&source=dukascopy&symbol=EURUSD")
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert api.get("/api/v1/ohlcv/?end=2025-01-06").data["count"] == 0


def test_staff_job_and_action_permissions(api):
    assert api.get("/api/v1/collectors/jobs/").status_code == 403
    assert api.post("/api/v1/collectors/actions/", {"action": "sync", "source": "cftc"}).status_code == 403


def test_health_checks_database(api):
    assert api.get("/api/v1/health/").data["database"] == "ready"
    from django.db import OperationalError
    with patch("marketdata.views.connection.cursor", side_effect=OperationalError("private")):
        response = api.get("/api/v1/health/")
    assert response.status_code == 503 and "private" not in str(response.data)


def test_export_endpoint(api, imported):
    response = api.get("/api/v1/export/ohlcv/?file_format=parquet")
    assert response.status_code == 200
    table = pq.read_table(io.BytesIO(b"".join(response.streaming_content)))
    assert table.num_rows == 1
    response.close()


def test_null_expiration_duplicates_rejected(db):
    Instrument.objects.create(exchange="CFE", symbol="VX", instrument_name="VX")
    with pytest.raises(IntegrityError), transaction.atomic():
        Instrument.objects.create(exchange="CFE", symbol="VX", instrument_name="VX")


def test_dashboard_requires_staff(api):
    assert api.get("/").status_code == 302


def test_dashboard_has_real_counts(db, client, imported):
    staff = get_user_model().objects.create_user(username="operator", is_staff=True)
    client.force_login(staff)
    response = client.get("/")
    assert response.status_code == 200
    assert response.context["total_records"] == 1
    assert b"EURUSD" in response.content

