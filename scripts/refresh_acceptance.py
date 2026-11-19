"""Refresh checks and dashboard snapshot against the isolated replay database."""
import json
import os
import sys
import time
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
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import Count
from django.test import Client, override_settings
from marketdata.models import CotReport, DataQualityIssue
from marketdata.quality import scan_quality
from marketdata.exports import write_parquet
import pyarrow.parquet as pq

call_command("migrate", interactive=False, verbosity=0)

started = time.monotonic()
added = scan_quality()
report["checks"]["quality_repeat_new_issues"] = added
report["checks"]["quality_scan_seconds"] = round(time.monotonic() - started, 3)
report["checks"]["quality_severity_counts"] = list(DataQualityIssue.objects.values("severity").annotate(count=Count("id")))
report["checks"]["quality_type_counts"] = list(DataQualityIssue.objects.values("issue_type").annotate(count=Count("id")))
with (workspace / "cot-with-positions.parquet").open("wb") as handle:
    write_parquet(CotReport.objects.order_by("id"), handle)
table = pq.read_table(workspace / "cot-with-positions.parquet", columns=["trader_positions"])
assert table.num_rows == 69888
assert json.loads(table[0][0].as_py())
report["checks"]["parquet_positions_retained"] = True
client = Client()
client.force_login(get_user_model().objects.get(username="acceptance_operator"))
with override_settings(ALLOWED_HOSTS=["testserver"]):
    response = client.get("/")
    assert response.status_code == 200
    (output / "dashboard-preview.html").write_bytes(response.content)
(output / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report["checks"], indent=2))

