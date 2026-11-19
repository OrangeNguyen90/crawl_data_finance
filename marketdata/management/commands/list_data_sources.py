from django.core.management.base import BaseCommand
from marketdata.sources import ensure_sources
from marketdata.models import DataSource


class Command(BaseCommand):
    help = "List registered market data providers"

    def handle(self, *args, **options):
        ensure_sources()
        for source in DataSource.objects.order_by("name"):
            self.stdout.write(f"{source.name}: {'enabled' if source.enabled else 'disabled'} ({source.license_status})")
