from django.core.management.base import BaseCommand, CommandError
from marketdata.models import CollectorJob, DataSource, SourceSchedule
from marketdata.sources import ensure_sources


class Command(BaseCommand):
    help = "Configure source enabled state and one database schedule, preserving license metadata"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--enable", action="store_true")
        group.add_argument("--disable", action="store_true")
        parser.add_argument("--interval-minutes", type=int)
        parser.add_argument("--max-retries", type=int, default=2)
        parser.add_argument("--disable-schedule", action="store_true")

    def handle(self, *args, **options):
        ensure_sources()
        try:
            source = DataSource.objects.get(name=options["source"])
        except DataSource.DoesNotExist:
            raise CommandError("Unknown source") from None
        interval = options["interval_minutes"]
        if interval is not None and (interval < 1 or source.name in {"dukascopy", "firstrate"}):
            raise CommandError("Positive interval required; manual import sources cannot be scheduled")
        if options["max_retries"] < 0 or options["max_retries"] > 10:
            raise CommandError("max-retries must be 0..10")
        if options["enable"] or options["disable"]:
            source.enabled = options["enable"]
            source.save(update_fields=["enabled", "updated_at"])
            if options["disable"]:
                CollectorJob.objects.filter(source=source, status__in=["queued", "claimed", "running"]).update(cancel_requested=True)
        if interval is not None:
            SourceSchedule.objects.update_or_create(source=source, defaults={"enabled": True,
                "interval_minutes": interval, "max_retries": options["max_retries"]})
        if options["disable_schedule"]:
            SourceSchedule.objects.filter(source=source).update(enabled=False)
        self.stdout.write(f"{source.name}: enabled={source.enabled}; license metadata unchanged")

