from django.core.management.base import BaseCommand, CommandError
from marketdata.collectors.registry import get_collector
from marketdata.sources import ensure_sources
from marketdata.models import DataSource


class Command(BaseCommand):
    help = "Check source discovery without importing records; nonzero exit on failure"

    def add_arguments(self, parser):
        parser.add_argument("--source")

    def handle(self, *args, **options):
        ensure_sources()
        sources = DataSource.objects.order_by("name")
        if options["source"]:
            sources = sources.filter(name=options["source"])
            if not sources.exists():
                raise CommandError("Unknown source")
        failed = False
        for source in sources:
            if source.name in {"dukascopy", "firstrate"}:
                self.stdout.write(f"{source.name}: manual CSV/ZIP import only")
                continue
            collector = get_collector(source.name)
            try:
                if source.name == "eurex":
                    collector.introspect()
                    self.stdout.write("eurex: GraphQL introspection reachable")
                elif source.name == "cboe":
                    rows = list(collector.parse(collector.fetch(collector.discover()[0])))
                    self.stdout.write(f"cboe: {len(rows)} parsed product aggregates")
                else:
                    urls = collector.discover()
                    if not urls:
                        raise ValueError
                    self.stdout.write(f"{source.name}: discovered {len(urls)} links; data parsing not certified")
            except Exception as exc:
                failed = True
                self.stderr.write(f"{source.name}: failed ({type(exc).__name__}); details suppressed")
            finally:
                collector.close()
        if failed:
            raise CommandError("One or more source checks failed")

