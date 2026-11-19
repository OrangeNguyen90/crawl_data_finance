"""Revalidate cached original archives without touching any database."""
import json
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from marketdata.collectors.cftc import CftcCollector, archive_details
collector = CftcCollector()
results = []
try:
    for path in (root / "live_evidence").glob("*2025.zip"):
        count = 0
        try:
            with path.open("rb") as handle:
                for row in collector.parse(handle):
                    collector.normalize(row, *archive_details(str(path))[1:])
                    count += 1
            results.append({"file": path.name, "status": "parsed", "records": count})
        except Exception as exc:
            results.append({"file": path.name, "status": "failed", "records": count, "error": type(exc).__name__})
finally:
    collector.close()
(root / "live_evidence/validation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))

