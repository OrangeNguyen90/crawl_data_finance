"""Strict CME public PG03 parser. Unsupported sections fail closed, raw PDF retained."""
import io
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from pypdf import PdfReader

from marketdata.collectors.base import CollectorError
from marketdata.collectors.statistics import StatisticsCollector

URL = "https://www.cmegroup.com/market-data/daily-bulletin.html"
# Only product identities verified against the official PG03 headings are enabled.
PRODUCTS = {"CORN FUT": ("CBOT", "CORN"), "OATS FUT": ("CBOT", "OATS"),
            "ROUGH RICE FUT": ("CBOT", "ROUGH_RICE"), "SOYBEAN FUT": ("CBOT", "SOYBEAN"),
            "WHEAT FUT": ("CBOT", "WHEAT")}
MONTHS = {m.upper(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


class CmeCollector(StatisticsCollector):
    source_name = "cme"
    allowed_host = "www.cmegroup.com"
    file_format = "pdf"

    def discover(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    href = dict(attrs).get("href", "")
                    if href.endswith("Section03_Agricultural_Futures.pdf"):
                        self.urls.append(urljoin(URL, href))
        parser = Links()
        parser.feed(self.fetch(URL).decode("utf-8"))
        for url in parser.urls:
            self._check_url(url)
        return sorted(set(parser.urls))

    def parse(self, content):
        handle = io.BytesIO(content) if isinstance(content, bytes) else content
        try:
            pdf = PdfReader(handle, strict=True)
            if pdf.is_encrypted or len(pdf.pages) > 50:
                raise CollectorError("Unsupported CME PDF")
            text = "\n".join(page.extract_text(extraction_mode="layout") for page in pdf.pages)
        except CollectorError:
            raise
        except Exception:
            raise CollectorError("CME PDF text extraction failed") from None
        yield from self.parse_text(text)

    def parse_text(self, text):
        dates = set(re.findall(r"(?:Mon|Tue|Wed|Thu|Fri),\s+([A-Z][a-z]{2}\s+\d{2},\s+\d{4})", text))
        statuses = set(re.findall(r"\b(PRELIMINARY|FINAL)\b", text))
        if len(dates) != 1 or len(statuses) != 1 or "AGRICULTURAL FUTURES" not in text:
            raise CollectorError("CME date, section or report status ambiguous")
        if not all(word in text for word in ("GLOBEX", "VOLUME", "INTEREST")):
            raise CollectorError("CME column headers not recognized")
        trading_date = datetime.strptime(next(iter(dates)), "%b %d, %Y").date()
        status = next(iter(statuses)).lower()
        current = None
        contracts = []
        output = []

        def qty(token, volume=False):
            if token == "----" and volume:
                return 0  # Explicit CME no-activity marker in volume columns only.
            if not re.fullmatch(r"\d+", token):
                raise CollectorError("Unexpected CME quantity marker")
            return int(token)

        def finish(total):
            nonlocal contracts
            if not contracts or len(total) not in (6, 7):
                raise CollectorError("CME product total structure changed")
            if total[3] in ("+", "-"):
                total = total[:3] + [total[3] + total[4]] + total[5:]
            elif total[3] == "UNCH":
                total[3] = "0"
            if (sum(r["volume"] for r in contracts) != qty(total[0], True) + qty(total[1], True)
                    or sum(r["open_interest"] for r in contracts) != qty(total[2])
                    or sum(r["change_in_oi"] for r in contracts) != int(total[3])):
                raise CollectorError("CME contract totals do not reconcile")
            output.extend(contracts)
            contracts = []

        for line in text.splitlines():
            line = " ".join(line.split())
            if line in PRODUCTS:
                if current is not None:
                    raise CollectorError("CME product total missing")
                current = line
                continue
            if current is None:
                continue
            if line.startswith("TOTAL " + current):
                finish(line[len("TOTAL " + current):].split())
                current = None
                continue
            if not re.match(r"^[A-Z]{3}\d{2}\s", line):
                continue
            parts = line.split()
            month = parts.pop(0)
            if month[:3] not in MONTHS:
                raise CollectorError("Unknown CME contract month")
            # Trailing fields: RTH vol, Globex vol, OI, OI change, year-ago vol/OI/settle.
            if len(parts) < 10:
                raise CollectorError("CME row too short")
            if parts[-5] in ("+", "-"):
                oi_change = int(parts[-5] + parts[-4])
                rth, globex, oi = parts[-8:-5]
            elif parts[-4] == "UNCH":
                oi_change = 0
                rth, globex, oi = parts[-7:-4]
            else:
                raise CollectorError("CME open interest change structure changed")
            exchange, product = PRODUCTS[current]
            contract_month = f"20{month[3:]}-{MONTHS[month[:3]]:02d}"
            contracts.append({"trading_date": trading_date, "exchange": exchange,
                "symbol": f"{product}:{contract_month}", "name": current,
                "contract_type": "future", "metadata": {"contract_month": contract_month},
                "volume": qty(rth, True) + qty(globex, True), "open_interest": qty(oi), "change_in_oi": oi_change,
                "report_status": status, "raw_fields": {"line": line}})
        if current is not None or not output:
            raise CollectorError("CME verified product totals missing")
        yield from output

