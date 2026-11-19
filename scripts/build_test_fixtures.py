"""Extract small actual-source format fixtures; keep original downloaded evidence ignored."""
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "marketdata/tests/fixtures"
provenance = []
for path in (root / "live_evidence").glob("*.zip"):
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.infolist()[0]) as binary, io.TextIOWrapper(binary, encoding="utf-8-sig") as text:
            reader = csv.reader(text)
            rows = [next(reader) for _ in range(3)]
    fixture = target / (path.stem + ".csv")
    with fixture.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    provenance.append({"file": fixture.name, "url": "https://www.cftc.gov/files/dea/history/" + path.name,
                       "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "data_rows": 2})
html = (root / "live_evidence/cboe.html").read_text(encoding="utf-8")
# Retain only the two exact observed summary tables, not site scripts or unrelated content.
import re
tables = re.findall(r"<table\b.*?</table>", html, flags=re.S)
selected = [t for t in tables if "CFE Futures Totals" in t or ">FUTURES<" in t]
(target / "cboe_summary.html").write_text("<h3>CFE Futures Price &amp; Volume Detail for 2026-11-03</h3>\n" + "\n".join(selected), encoding="utf-8")
provenance.append({"file": "cboe_summary.html", "url": "https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/",
                   "html_sha256": hashlib.sha256(html.encode()).hexdigest(), "note": "Two exact table excerpts; report heading date from document"})
(target / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
print("Created actual-source fixtures:", len(provenance))

