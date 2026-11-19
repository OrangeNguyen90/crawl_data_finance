"""Read-only official-source probe. Stores raw evidence locally, never bypasses HTTP errors."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from marketdata.collectors.cftc import CftcCollector, archive_details
from marketdata.collectors.base import BaseCollector

class Probe(BaseCollector):
    discover = parse = validate = normalize = persist = sync = backfill = lambda *args: None

target = ROOT / "live_evidence"
target.mkdir(exist_ok=True)
results = []
c = CftcCollector()
try:
    urls = c.discover()
    current = [u for u in urls if archive_details(u)[0] == 2025]
    for url in current:
        item = {"source": "cftc", "url": url}
        try:
            with c.fetch_file(url) as handle:
                path = target / Path(url).name
                with open(path, "wb") as out:
                    while chunk := handle.read(65536):
                        out.write(chunk)
            rows = 0
            types = archive_details(url)
            with path.open("rb") as handle:
                for row in c.parse(handle):
                    c.normalize(row, types[1], types[2])
                    rows += 1
            item.update(status="parsed", rows=rows)
        except Exception as exc:
            item.update(status="failed", error=type(exc).__name__)
        results.append(item)
except Exception as exc:
    results.append({"source": "cftc", "status": "failed", "error": type(exc).__name__})
finally:
    c.close()

for source, url, name in [
    ("cme", "https://www.cmegroup.com/market-data/daily-bulletin.html", "cme.html"),
    ("cme", "https://www.cmegroup.com/daily_bulletin/current/Section03_Agricultural_Futures.pdf", "cme03.pdf"),
    ("cboe", "https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/", "cboe.html"),
    ("eurex", "https://www.eurex.com/ex-en/data/free-reference-data-api", "eurex.html"),
]:
    p = Probe()
    p.allowed_host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).hostname
    try:
        content = p.fetch(url)
        (target / name).write_bytes(content)
        results.append({"source": source, "url": url, "status": "downloaded", "bytes": len(content)})
    except Exception as exc:
        results.append({"source": source, "url": url, "status": "failed", "error": type(exc).__name__})
    finally:
        p.close()
(target / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))

