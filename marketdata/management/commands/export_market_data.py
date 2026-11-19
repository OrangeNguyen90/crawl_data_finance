from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from marketdata.exports import DATASETS, csv_chunks, write_parquet
from marketdata.views import apply_filters, CotList, OpenInterestList, OhlcvList, InstrumentList


class Command(BaseCommand):
    help = "Export local datasets to bounded CSV or Parquet without loading the full queryset"

    def add_arguments(self, parser):
        parser.add_argument("--dataset", choices=list(DATASETS), required=True)
        parser.add_argument("--file-format", choices=["csv", "parquet"], default="csv")
        parser.add_argument("--output", required=True)
        for key in ("source", "start", "end", "symbol", "timeframe"):
            parser.add_argument("--" + key)

    def handle(self, *args, **options):
        definitions = {"cot": CotList, "open-interest": OpenInterestList, "ohlcv": OhlcvList, "instruments": InstrumentList}
        definition = definitions[options["dataset"]]
        try:
            query = apply_filters(DATASETS[options["dataset"]].objects.order_by("pk"),
                {k: options[k] for k in ("source", "start", "end", "symbol", "timeframe") if options[k]},
                definition.filters, definition.date_field)
            target = Path(options["output"]).resolve()
            if target.exists():
                raise CommandError("Output exists; choose a new filename")
            target.parent.mkdir(parents=True, exist_ok=True)
            if options["file_format"] == "csv":
                with target.open("x", encoding="utf-8", newline="") as handle:
                    for chunk in csv_chunks(query):
                        handle.write(chunk)
            else:
                with target.open("xb") as handle:
                    write_parquet(query, handle)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Export failed ({type(exc).__name__}); inspect parameters") from None
        self.stdout.write(f"Exported records={query.count()} to {target}")

