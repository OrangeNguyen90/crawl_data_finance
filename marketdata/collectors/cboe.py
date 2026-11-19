"""CFE public product aggregates. No DataShop access; no fabricated contract prices."""
import io
import re
from datetime import date
from html.parser import HTMLParser

from marketdata.collectors.base import CollectorError
from marketdata.collectors.statistics import StatisticsCollector, integer

URL = "https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/"


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


class CboeCollector(StatisticsCollector):
    source_name = "cboe"
    allowed_host = "www.cboe.com"

    def discover(self):
        return [URL]

    def parse(self, content):
        if hasattr(content, "read"):
            content = content.read()
        parser = Tables()
        parser.feed(content.decode("utf-8-sig"))
        match = re.search(r"CFE Futures Price & Volume Detail for\s+(\d{4}-\d{2}-\d{2})", " ".join(parser.text))
        if not match:
            raise CollectorError("CFE report date not recognized")
        trading_date = date.fromisoformat(match.group(1))
        expected = ["FUTURES", "Trade Volume", "Block Volume", "ECRP Volume", "Open Interest", "Change In Open Interest"]
        tables = [t for t in parser.tables if t and t[0] == expected]
        if len(tables) != 1 or len(tables[0]) < 2:
            raise CollectorError("CFE product statistics table schema not recognized")
        totals = [t for t in parser.tables if t and any(r and r[0] == "CFE Futures Totals" for r in t)]
        rows = []
        for row in tables[0][1:]:
            if len(row) != 6:
                raise CollectorError("CFE statistics row width changed")
            name, volume, block, ecrp, oi, change = row
            # Provider name identifies aggregate; it must not be presented as an expiring contract.
            symbol = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
            if len(symbol) > 100:
                raise CollectorError("CFE aggregate identifier too long")
            rows.append({"trading_date": trading_date, "exchange": "CFE", "symbol": symbol, "name": name,
                "volume": integer(volume), "open_interest": integer(oi), "change_in_oi": integer(change, True),
                "report_status": "unspecified", "contract_type": "product_aggregate",
                "metadata": {"scope": "product_aggregate", "includes_tas": "Includes TAS" in name},
                "raw_fields": dict(zip(expected, row))})
        if totals:
            total_rows = [r for t in totals for r in t if r and r[0] == "CFE Futures Totals"]
            if len(total_rows) != 1 or len(total_rows[0]) != 6:
                raise CollectorError("CFE totals table ambiguous")
            total = total_rows[0]
            if sum(r["volume"] for r in rows) != integer(total[1]) or sum(r["open_interest"] for r in rows) != integer(total[4]):
                raise CollectorError("CFE product totals do not reconcile")
        yield from rows

