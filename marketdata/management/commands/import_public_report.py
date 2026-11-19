from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from marketdata.collectors.base import CollectorError
from marketdata.collectors.registry import get_collector
from marketdata.models import CollectorCheckpoint, DataSource
from marketdata.runtime import fingerprint, issue, job_run, store_raw
from marketdata.sources import ensure_sources


class Command(BaseCommand):
    help = "Import a locally saved public CME PDF or Cboe HTML, retaining the original and provenance"

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=["cme", "cboe"], required=True)
        parser.add_argument("--file", required=True)
        parser.add_argument("--official-url", required=True)
        parser.add_argument("--published-at", help="Actual publication timestamp with explicit UTC offset, if supplied by source")

    def handle(self, *args, **options):
        ensure_sources()
        collector = get_collector(options["source"])
        source = DataSource.objects.get(name=options["source"])
        path = Path(options["file"])
        try:
            collector._check_url(options["official_url"])
            if not path.is_file() or path.stat().st_size > collector.max_bytes:
                raise CollectorError("Expected a bounded local report file")
            published = None
            if options["published_at"]:
                published = datetime.fromisoformat(options["published_at"])
                if published.tzinfo is None:
                    raise CollectorError("published-at must include a timezone offset")
            with job_run(source, "import", {"official_url": options["official_url"]}) as job:
                with path.open("rb") as handle:
                    raw = store_raw(source, handle, options["official_url"], path.name, collector.file_format)
                if published is not None:
                    raw.source_published_at = published
                    raw.save(update_fields=["source_published_at"])
                job.records_downloaded = 1
                key = fingerprint({"source": source.name, "url": options["official_url"], "digest": raw.sha256})
                if not CollectorCheckpoint.objects.filter(source=source, key=key).exists():
                    try:
                        with transaction.atomic(), open(raw.storage_path, "rb") as handle:
                            inserted, updated, rejected = collector.persist(collector.parse(handle), raw)
                            if inserted + updated == 0:
                                raise CollectorError("No verified report rows recognized")
                            raw.processing_status = "complete"
                            raw.save(update_fields=["processing_status"])
                            CollectorCheckpoint.objects.get_or_create(source=source, key=key, defaults={"raw_file": raw})
                        job.records_inserted, job.records_updated, job.records_rejected = inserted, updated, rejected
                    except BaseException as exc:
                        raw.processing_status = "quarantined"
                        raw.save(update_fields=["processing_status"])
                        issue(source, "daily_statistics", "file_failure", f"raw={raw.pk}: {type(exc).__name__}")
                        raise
        except CollectorError as exc:
            raise CommandError(str(exc)) from None
        except Exception as exc:
            raise CommandError(f"Report import failed ({type(exc).__name__}); details suppressed") from None
        finally:
            collector.close()
        self.stdout.write(f"job={job.pk} {job.status}: inserted={job.records_inserted} updated={job.records_updated}")

