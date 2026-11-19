from datetime import date
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector, archive_details
from marketdata.sources import ensure_sources


class Command(BaseCommand):
    help = "Replay a previously downloaded official CFTC archive without a new network request"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--official-url", required=True)
        parser.add_argument("--start")
        parser.add_argument("--end")
        parser.add_argument("--market-code")

    def handle(self, *args, **options):
        path = Path(options["file"])
        collector = CftcCollector()
        try:
            collector._check_url(options["official_url"])
            details = archive_details(options["official_url"])
            if not details or not path.is_file() or path.stat().st_size > collector.max_bytes:
                raise CollectorError("Expected a bounded local archive and its verified official archive URL")
            start = date.fromisoformat(options["start"]) if options["start"] else date(details[0], 1, 1)
            end = date.fromisoformat(options["end"]) if options["end"] else date(details[0], 12, 31)
            ensure_sources()
            collector.discover = lambda: [options["official_url"]]
            collector.download = lambda url: path.open("rb")
            job = collector.backfill(start, end, market_code=options["market_code"])
        except CollectorError as exc:
            raise CommandError(str(exc)) from None
        except Exception as exc:
            raise CommandError(f"Archive replay failed ({type(exc).__name__}); details suppressed") from None
        finally:
            collector.close()
        self.stdout.write(f"job={job.pk} {job.status}: inserted={job.records_inserted} updated={job.records_updated} rejected={job.records_rejected}")
        if job.status == "partial":
            raise CommandError("Archive contains quarantined rows")

