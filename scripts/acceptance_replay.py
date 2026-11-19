"""Real-source replay in a NEW isolated SQLite acceptance DB. Never touches production.
Network availability is reported separately by live_probe.py. This is not PostgreSQL certification.
"""
import io
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "live_evidence"
OUTPUT.mkdir(exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix="marketdata-acceptance-"))
os.environ["MARKETDATA_SQLITE_TEST"] = "1"
os.environ["MARKETDATA_SQLITE_PATH"] = str(workspace / "acceptance.sqlite3")
os.environ["MARKETDATA_RAW_ROOT"] = str(workspace / "raw")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, override_settings
from marketdata.collectors.cftc import CftcCollector, archive_details
from marketdata.collectors.cboe import CboeCollector, URL as CBOE_URL
from marketdata.exports import csv_chunks, write_parquet
from marketdata.models import CollectorJob, CotReport, DataSource, FuturesDailyStatistic
from marketdata.runtime import store_raw
from marketdata.sources import ensure_sources

report = {"backend": "sqlite_isolated_acceptance_only", "workspace": str(workspace),
          "production_records_inserted": 0, "source_archive_replay": [], "cboe": {}, "checks": {}}
call_command("migrate", interactive=False, verbosity=0)
call_command("check", verbosity=0)
ensure_sources()
for path in sorted(OUTPUT.glob("*2025.zip")):
    c = CftcCollector()
    url = "https://www.cftc.gov/files/dea/history/" + path.name
    c.discover = lambda: [url]
    c.download = lambda url, path=path: path.open("rb")
    try:
        first = c.backfill(date(2025, 1, 1), date(2025, 12, 31))
        repeat = c.backfill(date(2025, 1, 1), date(2025, 12, 31))
        assert first.status == "success" and first.records_rejected == 0
        assert repeat.records_inserted == repeat.records_updated == 0
        report["source_archive_replay"].append({"file": path.name, "inserted": first.records_inserted,
            "updated": first.records_updated, "rejected": first.records_rejected, "repeated_run_writes": 0})
    finally:
        c.close()
assert len(report["source_archive_replay"]) == 6, "Six downloaded CFTC archives required"
report["checks"]["cftc_database_count"] = CotReport.objects.count()
source = DataSource.objects.get(name="cboe")
source.enabled = True
source.save(update_fields=["enabled"])
raw = store_raw(source, (OUTPUT / "cboe.html").read_bytes(), CBOE_URL, "cboe.html", "html")
collector = CboeCollector()
rows = list(collector.parse((OUTPUT / "cboe.html").read_bytes()))
first = collector.persist(iter(rows), raw)
repeat = collector.persist(iter(rows), raw)
assert FuturesDailyStatistic.objects.count() == len(rows) == 12
report["cboe"] = {"inserted": first[0], "repeated_count": FuturesDailyStatistic.objects.count(),
                   "scope": "product_aggregate", "report_date": str(rows[0]["trading_date"])}
collector.close()

import pyarrow.parquet as pq
target = workspace / "cot.parquet"
with target.open("wb") as out:
    write_parquet(CotReport.objects.order_by("id"), out)
assert pq.read_metadata(target).num_rows == CotReport.objects.count()
with (workspace / "cot.csv").open("w", encoding="utf-8", newline="") as out:
    for chunk in csv_chunks(CotReport.objects.order_by("id")):
        out.write(chunk)
report["checks"]["csv_export_rows"] = CotReport.objects.count()
report["checks"]["parquet_export_rows"] = pq.read_metadata(target).num_rows

staff = get_user_model().objects.create_user(username="acceptance_operator", is_staff=True)
client = Client()
client.force_login(staff)
with override_settings(ALLOWED_HOSTS=["testserver"]):
    response = client.get("/")
    assert response.status_code == 200
    (OUTPUT / "dashboard-preview.html").write_bytes(response.content)
    overview = client.get("/api/v1/overview/").json()
    assert overview["total_records"] == CotReport.objects.count() + 12
    assert client.get("/api/v1/cot/?start=invalid").status_code == 400
    assert client.get("/api/v1/health/").status_code == 200
report["checks"]["dashboard_records"] = overview["total_records"]
report["checks"]["api_invalid_date"] = 400
report["checks"]["isolated_health"] = 200
(OUTPUT / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))

