from django.core.management.base import BaseCommand
from marketdata.quality import scan_quality


class Command(BaseCommand):
    help = "Detect quality issues without changing market records"

    def handle(self, *args, **options):
        self.stdout.write(f"New quality issues: {scan_quality()}")

