from marketdata.collectors.base import CollectorError
from marketdata.collectors.csv_import import CsvCollector


class DukascopyCollector(CsvCollector):
    source_name = "dukascopy"
    allowed_host = "www.dukascopy.com"

    def normalize(self, row, report_type=None, scope=None, manifest=None):
        result = super().normalize(row, manifest=manifest)
        if any(result[key] <= 0 for key in ("open", "high", "low", "close")):
            raise CollectorError("FX spot prices must be positive")
        return result

    def validate_manifest(self, manifest):
        super().validate_manifest(manifest)
        if manifest["exchange"] != "DUKASCOPY_FX" or manifest["asset_class"] != "fx_spot":
            raise CollectorError("Dukascopy import is FX spot; use exchange DUKASCOPY_FX and asset_class fx_spot")
        if manifest["price_type"] not in {"bid", "ask"}:
            raise CollectorError("Dukascopy bid/ask must be explicit")
        if manifest["volume_type"] not in {"quote", "unknown"}:
            raise CollectorError("Dukascopy volume must not be labelled exchange trade volume")

