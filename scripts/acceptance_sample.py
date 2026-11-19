"""Import the public FirstRate sample into the existing isolated acceptance DB only."""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
output = root / "live_evidence"
report = json.loads((output / "acceptance.json").read_text(encoding="utf-8"))
workspace = Path(report["workspace"])
os.environ["MARKETDATA_SQLITE_TEST"] = "1"
os.environ["MARKETDATA_SQLITE_PATH"] = str(workspace / "acceptance.sqlite3")
os.environ["MARKETDATA_RAW_ROOT"] = str(workspace / "raw")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from marketdata.collectors.firstrate import FirstRateCollector
from marketdata.models import DataSource, OhlcvBar
from marketdata.exports import write_parquet
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from marketdata.quality import scan_quality

path = output / "firstrate_ES_sample.zip"
member = "ES_1min_sample.csv"
with zipfile.ZipFile(path) as archive:
    with archive.open(member) as binary:
        lines = binary.read().decode("utf-8-sig").splitlines()
    start, end = lines[1][:10], lines[-1][:10]
manifest = {"symbol": "ES_SAMPLE_CONTINUOUS", "name": "FirstRate ES SAMPLE continuous series",
    "exchange": "CME", "asset_class": "future", "contract_type": "continuous_future", "currency": "USD",
    "timeframe": "1m", "timezone": "America/New_York", "price_type": "trade", "volume_type": "trade",
    "source_url": "https://firstratedata.com/i/futures/ES",
    "download_url": "https://frd001.s3.us-east-2.amazonaws.com/frd_sample_futures_ES.zip",
    "license_url": "https://firstratedata.com/about/license", "license_status": "permitted",
    "usage": "private_sample_evaluation_only", "sample": True, "start": start, "end": end,
    "adjustment_method": "unspecified_by_sample_filename", "member": member}
source = DataSource.objects.get(name="firstrate")
source.enabled = True
source.save(update_fields=["enabled"])
collector = FirstRateCollector()
job = collector.import_file(path, manifest)
repeat = collector.import_file(path, manifest)
assert job.status == "success" and job.records_inserted == len(lines) - 1 and job.records_rejected == 0
assert repeat.records_inserted == repeat.records_updated == 0
with (workspace / "sample.parquet").open("wb") as handle:
    write_parquet(OhlcvBar.objects.all(), handle)
collector.close()
new_issues = scan_quality()
staff = get_user_model().objects.get(username="acceptance_operator")
client = Client()
client.force_login(staff)
with override_settings(ALLOWED_HOSTS=["testserver"]):
    response = client.get("/")
    assert response.status_code == 200
    (output / "dashboard-preview.html").write_bytes(response.content)
    overview = client.get("/api/v1/overview/").json()
report["firstrate_sample"] = {"inserted": job.records_inserted, "rejected": job.records_rejected,
    "start": start, "end": end, "timeframe": "1m", "repeat_writes": 0, "license": "private_sample_evaluation"}
report["checks"]["dashboard_records"] = overview["total_records"]
report["checks"]["quality_issues_created"] = new_issues
(output / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report["firstrate_sample"], indent=2))
print("Dashboard real-source records:", overview["total_records"])
print("Quality issues created:", new_issues)

