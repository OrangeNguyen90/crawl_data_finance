import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from marketdata.collectors.base import CollectorError
from marketdata.collectors.dukascopy import DukascopyCollector
from marketdata.collectors.firstrate import FirstRateCollector
from marketdata.sources import ensure_sources


class Command(BaseCommand):
    help = "Import an explicitly licensed local CSV/ZIP with a provenance manifest"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, choices=["dukascopy", "firstrate"])
        parser.add_argument("--file", required=True)
        parser.add_argument("--manifest", required=True)

    def handle(self, *args, **options):
        ensure_sources()
        collector = (DukascopyCollector if options["source"] == "dukascopy" else FirstRateCollector)()
        try:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8-sig"))
            job = collector.import_file(options["file"], manifest)
        except CollectorError as exc:
            raise CommandError(str(exc)) from None
        except Exception as exc:
            raise CommandError(f"Import failed ({type(exc).__name__}); details suppressed") from None
        finally:
            collector.close()
        self.stdout.write(f"job={job.pk} {job.status}: inserted={job.records_inserted} updated={job.records_updated} rejected={job.records_rejected}")

