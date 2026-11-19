from marketdata.collectors.base import CollectorError
from marketdata.collectors.csv_import import CsvCollector


class FirstRateCollector(CsvCollector):
    source_name = "firstrate"
    allowed_host = "firstratedata.com"

    def validate_manifest(self, manifest):
        super().validate_manifest(manifest)
        if manifest.get("sample") is not True or not all(manifest.get(k) for k in ("start", "end", "adjustment_method")):
            raise CollectorError("FirstRate requires SAMPLE=true, date range and adjustment_method")
        if manifest["start"] > manifest["end"]:
            raise CollectorError("Invalid sample date range")

