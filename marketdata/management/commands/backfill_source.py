from datetime import date
from django.core.management.base import BaseCommand, CommandError
from marketdata.collectors.base import CollectorError
from marketdata.collectors.registry import get_collector
from marketdata.sources import ensure_sources


class Command(BaseCommand):
    help = "Backfill discovered historical reports by year or inclusive date range"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--year", type=int)
        parser.add_argument("--start")
        parser.add_argument("--end")
        parser.add_argument("--report-type", choices=["legacy", "disaggregated", "tff"])
        parser.add_argument("--scope", choices=["futures_only", "combined"])
        parser.add_argument("--market-code")

    def handle(self, *args, **options):
        try:
            if options["year"]:
                if options["start"] or options["end"]:
                    raise ValueError
                start, end = date(options["year"], 1, 1), date(options["year"], 12, 31)
            else:
                start, end = date.fromisoformat(options["start"] or ""), date.fromisoformat(options["end"] or "")
            if start > end:
                raise ValueError
        except ValueError:
            raise CommandError("Use --year OR --start/--end YYYY-MM-DD with start <= end") from None
        ensure_sources()
        collector = get_collector(options["source"])
        try:
            filters = {k: options[k] for k in ("report_type", "scope", "market_code") if options[k]}
            if filters and options["source"] != "cftc":
                raise CollectorError("COT filters are supported only for CFTC")
            job = collector.backfill(start, end, **filters)
        except CollectorError as exc:
            raise CommandError(str(exc)) from None
        except Exception as exc:
            raise CommandError(f"Backfill failed ({type(exc).__name__}); details suppressed") from None
        finally:
            collector.close()
        self.stdout.write(f"job={job.pk} {job.status}: inserted={job.records_inserted} updated={job.records_updated} rejected={job.records_rejected}")
        if job.status == "partial":
            raise CommandError("Some records were quarantined; inspect data quality issues")

