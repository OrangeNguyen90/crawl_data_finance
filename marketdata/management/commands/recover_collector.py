from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from marketdata.models import CollectorJob, CollectorLock, DataSource, RawDataFile


class Command(BaseCommand):
    help = "Recover abandoned work only AFTER the worker process has been stopped"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--worker-stopped", action="store_true")
        parser.add_argument("--owner", help="Exact lock owner UUID from Django admin")
        parser.add_argument("--job-id", type=int, help="Claimed orphan without a lock")

    def handle(self, *args, **options):
        if not options["worker_stopped"]:
            raise CommandError("Stop the owning worker first, then pass --worker-stopped")
        with transaction.atomic():
            source = DataSource.objects.select_for_update().get(name=options["source"])
            lock = CollectorLock.objects.filter(source=source).first()
            if lock:
                if str(lock.owner) != options["owner"]:
                    raise CommandError("Exact --owner UUID required; no changes made")
                CollectorJob.objects.filter(source=source, status__in=["running", "claimed"]).update(
                    status="failed", finished_at=timezone.now(), error_message="Abandoned worker recovered explicitly")
                lock.delete()
            else:
                count = CollectorJob.objects.filter(pk=options["job_id"], source=source, status="claimed").update(
                    status="failed", finished_at=timezone.now(), error_message="Orphaned queue claim recovered explicitly")
                if not count:
                    raise CommandError("No matching abandoned lock or claimed job; no changes made")
            RawDataFile.objects.filter(source=source, processing_status="processing").update(processing_status="failed")
        self.stdout.write("Recovered abandoned bookkeeping; rerun the original job to resume committed checkpoints")

