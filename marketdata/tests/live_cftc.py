"""Explicit live-source check. No fixtures, no database writes."""
import argparse
from datetime import date
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from marketdata.collectors.cftc import CftcCollector, archive_details


def main(year=2025):
    collector = CftcCollector()
    try:
        urls = [url for url in collector.discover() if archive_details(url)[0] == year]
        if len(urls) != 6:
            raise RuntimeError(f"Expected six official annual COT archives, found {len(urls)}")
        for url in urls:
            _, report_type, scope = archive_details(url)
            count = 0
            with collector.fetch_file(url) as handle:
                for row in collector.parse(handle):
                    first = collector.normalize(row, report_type, scope)
                    if first["report_date"] > date.today() or not first["market_code"]:
                        raise RuntimeError("Invalid live COT record")
                    count += 1
            if count == 0:
                raise RuntimeError("Empty live archive")
            print(f"PARSED {report_type} {scope}: records={count}")
    finally:
        collector.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    main(parser.parse_args().year)

