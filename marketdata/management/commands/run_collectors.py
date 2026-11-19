from django.core.management.base import BaseCommand, CommandError
from marketdata.jobs import execute_next, retry_failed, schedule_due


class Command(BaseCommand):
    help = "One bounded worker tick. Use a single Windows Task Scheduler entry to repeat."

    def add_arguments(self, parser):
        parser.add_argument("--schedule", action="store_true")
        parser.add_argument("--retry-failed", action="store_true")
        parser.add_argument("--max-jobs", type=int, default=4)

    def handle(self, *args, **options):
        if options["schedule"]:
            schedule_due()
        if options["retry_failed"]:
            retry_failed()
        failed = False
        for _ in range(max(0, min(options["max_jobs"], 100))):
            job = execute_next()
            if job is None:
                break
            self.stdout.write(f"job={job.pk} status={job.status} inserted={job.records_inserted} updated={job.records_updated}")
            failed = failed or job.status in {"failed", "partial"}
        if failed:
            raise CommandError("Worker tick finished with failed/partial jobs; inspect the database job log")

