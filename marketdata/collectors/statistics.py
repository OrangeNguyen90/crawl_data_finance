"""Shared daily-statistics persistence; product totals are explicitly aggregates."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction

from marketdata.collectors.base import BaseCollector, CollectorError
from marketdata.models import CollectorCheckpoint, DataSource, FuturesDailyStatistic, Instrument, SourceInstrumentMapping
from marketdata.runtime import check_cancel, fingerprint, issue, job_run, store_raw


def integer(value, signed=False):
    text = str(value).replace(",", "").strip()
    try:
        number = Decimal(text)
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError
        result = int(number)
        if abs(result) > 9223372036854775807 or (not signed and result < 0):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise CollectorError("Invalid daily statistics integer") from None


def instrument_for(source, exchange, symbol, name, contract_type, metadata=None, expiration=None, verification_status="verified"):
    if not exchange or not symbol or len(symbol) > 100:
        raise CollectorError("Missing or oversized instrument identity")
    if len(exchange) > 40 or len(f"{exchange}:{symbol}") > 100:
        raise CollectorError("Instrument identity exceeds the database canonical symbol limit")
    obj, _ = Instrument.objects.get_or_create(exchange=exchange, symbol=symbol, expiration_date=expiration,
        defaults={"instrument_name": name[:255], "canonical_symbol": f"{exchange}:{symbol}",
                  "contract_type": contract_type, "metadata": metadata or {}})
    if obj.contract_type != contract_type:
        raise CollectorError("Instrument contract type conflicts with existing metadata")
    # This maps a provider's exact identifier to its own instrument; never links by similar names.
    SourceInstrumentMapping.objects.get_or_create(source=source, source_symbol=symbol, instrument=obj,
        mapping_type="provider_report_identity", defaults={"verification_status": verification_status})
    return obj


class StatisticsCollector(BaseCollector):
    source_name = ""
    file_format = "html"

    def validate(self, row):
        required = {"trading_date", "exchange", "symbol", "name", "volume", "open_interest", "report_status"}
        if not required.issubset(row) or row["report_status"] not in {"preliminary", "final", "unspecified"}:
            raise CollectorError("Invalid statistics schema or report status")
        if not isinstance(row["trading_date"], date):
            raise CollectorError("Invalid trading date")
        integer(row["volume"])
        integer(row["open_interest"])

    def normalize(self, row, report_type=None, scope=None):
        self.validate(row)
        return row

    def persist(self, rows, source_file):
        inserted = updated = 0
        with transaction.atomic():
            for row in rows:
                self.validate(row)
                instrument = instrument_for(source_file.source, row["exchange"], row["symbol"], row["name"],
                    row.get("contract_type", "product_aggregate"), row.get("metadata"))
                _, created = FuturesDailyStatistic.objects.update_or_create(
                    instrument=instrument, source=source_file.source, trading_date=row["trading_date"],
                    report_status=row["report_status"], defaults={"source_file": source_file,
                        "volume": integer(row["volume"]), "open_interest": integer(row["open_interest"]),
                        "change_in_oi": integer(row["change_in_oi"], True) if row.get("change_in_oi") is not None else None,
                        "raw_fields": row.get("raw_fields", {})})
                inserted += int(created)
                updated += int(not created)
        return inserted, updated, 0

    def sync(self, job=None, **filters):
        source = DataSource.objects.get(name=self.source_name)
        with job_run(source, "sync", filters, job, transport=self) as running:
            urls = self.discover()
            if not urls:
                raise CollectorError("No verified public report links found")
            for url in urls:
                check_cancel(running)
                with self.fetch_file(url) as handle:
                    raw = store_raw(source, handle, url, url.rsplit("/", 1)[-1] or "report.html", self.file_format)
                running.records_downloaded += 1
                key = fingerprint({"url": url, "adapter": self.source_name})
                previous = CollectorCheckpoint.objects.filter(source=source, key=key).first()
                if previous and previous.raw_file_id == raw.pk:
                    continue
                try:
                    with transaction.atomic(), open(raw.storage_path, "rb") as handle:
                        counts = self.persist(self.parse(handle), raw)
                        if counts[0] + counts[1] == 0:
                            raise CollectorError("No verified statistics rows recognized")
                        raw.processing_status = "complete"
                        raw.save(update_fields=["processing_status"])
                        CollectorCheckpoint.objects.update_or_create(source=source, key=key,
                            defaults={"raw_file": raw, "metadata": {}})
                    running.records_inserted += counts[0]
                    running.records_updated += counts[1]
                    running.retry_count = max(running.retry_count, self.retry_count)
                    running.save(update_fields=["records_downloaded", "records_inserted", "records_updated", "records_rejected", "retry_count"])
                except BaseException as exc:
                    raw.processing_status = "quarantined"
                    raw.save(update_fields=["processing_status"])
                    issue(source, "daily_statistics", "schema_or_file_failure", f"raw={raw.pk}: {type(exc).__name__}")
                    raise
        return running

    def backfill(self, start, end, **kwargs):
        raise CollectorError("Historical report discovery is not verified for this adapter; no dates were fabricated")

