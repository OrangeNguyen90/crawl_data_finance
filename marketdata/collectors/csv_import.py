"""Explicit-manifest CSV/ZIP OHLC import. All price and time semantics are supplied."""
import csv
import io
import json
import re
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction

from marketdata.collectors.base import BaseCollector, CollectorError
from marketdata.collectors.statistics import instrument_for
from marketdata.models import CollectorCheckpoint, DataSource, OhlcvBar, QuarantinedRecord
from marketdata.runtime import check_cancel, fingerprint, issue, job_run, store_raw

TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}


def decimal_value(value, nullable=False):
    if value == "" and nullable:
        return None
    try:
        result = Decimal(value)
        if not result.is_finite() or abs(result) >= Decimal("1e16") or result.as_tuple().exponent < -8:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise CollectorError("Nonfinite or unrepresentable OHLCV value") from None


def utc_timestamp(text, zone, fmt=None):
    try:
        dt = datetime.strptime(text, fmt) if fmt else datetime.fromisoformat(text)
    except ValueError:
        raise CollectorError("Timestamp does not match the declared format") from None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    try:
        tz = ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise CollectorError("Unknown IANA timezone") from None
    first, second = dt.replace(tzinfo=tz, fold=0), dt.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise CollectorError("Ambiguous or nonexistent local time; supply an explicit UTC offset")
    if first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != dt:
        raise CollectorError("Nonexistent local time")
    return first.astimezone(timezone.utc)


class CsvCollector(BaseCollector):
    source_name = ""
    columns = ["timestamp", "open", "high", "low", "close", "volume"]

    def discover(self):
        return []

    def sync(self, **kwargs):
        raise CollectorError("This source uses local CSV/ZIP import with an explicit manifest")

    def backfill(self, start, end, **kwargs):
        return self.sync()

    def validate_manifest(self, manifest):
        for key in ("symbol", "exchange", "timeframe", "timezone", "price_type", "volume_type", "source_url", "license_status", "asset_class"):
            if not manifest.get(key):
                raise CollectorError(f"Import manifest requires {key}")
        if manifest["timeframe"] not in TIMEFRAMES:
            raise CollectorError("Unsupported timeframe")
        if manifest["license_status"] != "permitted":
            raise CollectorError("Import requires an explicitly permitted dataset license")
        parsed = urlparse(manifest["source_url"])
        if parsed.scheme != "https" or parsed.hostname not in {self.allowed_host, "www." + self.allowed_host.removeprefix("www.")} or parsed.username or parsed.password:
            raise CollectorError("Manifest source URL must identify the official provider")
        if manifest["price_type"] not in {"bid", "ask", "trade", "mid"}:
            raise CollectorError("Unknown price type")
        if manifest["volume_type"] not in {"quote", "trade", "tick", "unknown"}:
            raise CollectorError("Unknown volume type")
        if not re.fullmatch(r"[A-Za-z0-9_./:+-]{1,100}", manifest["symbol"]):
            raise CollectorError("Invalid instrument symbol")
        try:
            ZoneInfo(manifest["timezone"])
            for key in ("start", "end"):
                if manifest.get(key):
                    date.fromisoformat(manifest[key])
        except (ValueError, ZoneInfoNotFoundError):
            raise CollectorError("Invalid manifest timezone or date range") from None

    @contextmanager
    def text_stream(self, content, manifest):
        handle = io.BytesIO(content) if isinstance(content, bytes) else content
        handle.seek(0)
        if zipfile.is_zipfile(handle):
            with zipfile.ZipFile(handle) as archive:
                members = [m for m in archive.infolist() if m.filename.lower().endswith((".csv", ".txt")) and not m.is_dir() and "readme" not in m.filename.lower()]
                if manifest.get("member"):
                    members = [m for m in members if m.filename == manifest["member"]]
                if len(members) != 1:
                    raise CollectorError("Import ZIP must contain exactly one data CSV/TXT")
                member = members[0]
                if member.file_size > 500 * 1024 * 1024 or member.compress_size == 0 or member.file_size / member.compress_size > 200 or member.flag_bits & 1:
                    raise CollectorError("Unsafe import archive")
                with archive.open(member) as binary, io.TextIOWrapper(binary, encoding=manifest.get("encoding", "utf-8-sig"), newline="") as text:
                    yield text
        else:
            handle.seek(0)
            text = io.TextIOWrapper(handle, encoding=manifest.get("encoding", "utf-8-sig"), newline="")
            try:
                yield text
            finally:
                text.detach()

    def parse(self, content, manifest=None):
        manifest = manifest or {}
        with self.text_stream(content, manifest) as text:
            reader = csv.reader(text, delimiter=manifest.get("delimiter", ","), strict=True)
            columns = list(manifest.get("columns", self.columns))
            if manifest.get("header", True):
                header = next(reader, [])
                columns = [re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_") for h in header]
                aliases = {"time_utc": "timestamp", "gmt_time": "timestamp", "local_time": "timestamp", "datetime": "timestamp", "time": "timestamp", "date_time": "timestamp"}
                columns = [aliases.get(c, c) for c in columns]
                if len(columns) != len(set(columns)) or not set(self.columns[:5]).issubset(columns):
                    raise CollectorError("Unexpected import CSV header")
            for number, values in enumerate(reader, 2 if manifest.get("header", True) else 1):
                if not values:
                    continue
                if len(values) != len(columns):
                    raise CollectorError("Import CSV row width changed")
                yield number, dict(zip(columns, values))

    def validate(self, row):
        if not all(k in row for k in self.columns[:5]):
            raise CollectorError("Missing OHLC fields")

    def normalize(self, row, report_type=None, scope=None, manifest=None):
        manifest = manifest or {}
        self.validate(row)
        prices = {k: decimal_value(row[k]) for k in ("open", "high", "low", "close")}
        if prices["high"] < max(prices["open"], prices["close"], prices["low"]) or prices["low"] > min(prices["open"], prices["close"]):
            raise CollectorError("OHLC bounds are inconsistent")
        volume = decimal_value(row.get("volume", ""), nullable=True)
        if volume is not None and volume < 0:
            raise CollectorError("Negative OHLCV volume")
        stamp = utc_timestamp(row["timestamp"], manifest["timezone"], manifest.get("timestamp_format"))
        local_date = stamp.astimezone(ZoneInfo(manifest["timezone"])).date().isoformat()
        if manifest.get("start") and local_date < manifest["start"]:
            raise CollectorError("Record precedes declared sample date range")
        if manifest.get("end") and local_date > manifest["end"]:
            raise CollectorError("Record exceeds declared sample date range")
        return {**prices, "volume": volume, "timestamp_utc": stamp,
                "timeframe": manifest["timeframe"], "price_type": manifest["price_type"],
                "volume_type": manifest["volume_type"], "raw_fields": {"row": row, "manifest": manifest}}

    @transaction.atomic
    def persist(self, rows, source_file, instrument=None):
        if instrument is None:
            raise CollectorError("Import requires an explicit instrument")
        inserted = updated = 0
        batch = []
        seen = {}
        duplicates = 0
        unique = ["instrument", "timeframe", "timestamp_utc", "price_type", "source"]
        def flush(batch):
            existing = set(OhlcvBar.objects.filter(instrument=instrument, source=source_file.source,
                timeframe=batch[0]["timeframe"], price_type=batch[0]["price_type"],
                timestamp_utc__in=[r["timestamp_utc"] for r in batch]).values_list("timestamp_utc", flat=True))
            by_time = {}
            for row in batch:
                stamp = row["timestamp_utc"]
                if stamp in by_time and by_time[stamp] != row:
                    raise CollectorError("Conflicting OHLCV timestamp within file")
                by_time[stamp] = row
            OhlcvBar.objects.bulk_create([OhlcvBar(instrument=instrument, source=source_file.source,
                source_file=source_file, **r) for r in by_time.values()], batch_size=500,
                update_conflicts=True, unique_fields=unique,
                update_fields=["open", "high", "low", "close", "volume", "volume_type", "source_file", "raw_fields"])
            changed = len(set(by_time) & existing)
            return len(by_time) - changed, changed
        for row in rows:
            stamp = row["timestamp_utc"]
            digest = fingerprint(row)
            if stamp in seen:
                if seen[stamp] != digest:
                    raise CollectorError("Conflicting OHLCV timestamp across file batches")
                duplicates += 1
                continue
            seen[stamp] = digest
            batch.append(row)
            if len(batch) == 500:
                added, changed = flush(batch)
                inserted += added
                updated += changed
                batch.clear()
        if batch:
            added, changed = flush(batch)
            inserted += added
            updated += changed
        if duplicates:
            issue(source_file.source, "ohlcv", "duplicate_records", f"raw={source_file.pk}: {duplicates} identical duplicate rows skipped", "INFO")
        return inserted, updated, 0

    def import_file(self, path, manifest):
        self.validate_manifest(manifest)
        source = DataSource.objects.get(name=self.source_name)
        path = Path(path)
        if path.stat().st_size > self.max_bytes:
            raise CollectorError("Import file exceeds size limit")
        with job_run(source, "import", {"manifest": manifest}) as running:
            with path.open("rb") as handle:
                raw = store_raw(source, handle, manifest["source_url"], path.name, "zip" if path.suffix.lower() == ".zip" else "csv", manifest)
            running.records_downloaded = 1
            key = fingerprint({"digest": raw.sha256, "manifest": manifest})
            if CollectorCheckpoint.objects.filter(source=source, key=key).exists():
                return running
            rejected = 0
            try:
                with transaction.atomic():
                    instrument = instrument_for(source, manifest["exchange"], manifest["symbol"], manifest.get("name", manifest["symbol"]),
                        "fx_spot" if self.source_name == "dukascopy" else manifest.get("contract_type", "sample"),
                        {"asset_class": manifest["asset_class"], "sample": self.source_name == "firstrate"},
                        verification_status="user_declared")
                    instrument.asset_class = manifest["asset_class"]
                    instrument.currency = manifest.get("currency", "")
                    instrument.metadata = {**instrument.metadata, "last_import": manifest}
                    instrument.save(update_fields=["asset_class", "currency", "metadata"])
                    def rows():
                        nonlocal rejected
                        with open(raw.storage_path, "rb") as handle:
                            for number, row in self.parse(handle, manifest):
                                if number % 500 == 0:
                                    check_cancel(running)
                                try:
                                    yield self.normalize(row, manifest=manifest)
                                except CollectorError as exc:
                                    rejected += 1
                                    QuarantinedRecord.objects.update_or_create(source_file=raw, row_number=number,
                                        defaults={"payload": row, "reason": str(exc)})
                                    issue(source, "ohlcv", "invalid_record", f"raw={raw.pk} row={number}: {exc}")
                    counts = self.persist(rows(), raw, instrument)
                    if not counts[0] + counts[1] and not rejected:
                        raise CollectorError("Empty CSV import")
                    raw.processing_status = "partial" if rejected else "complete"
                    raw.save(update_fields=["processing_status"])
                    if not rejected:
                        CollectorCheckpoint.objects.get_or_create(source=source, key=key, defaults={"raw_file": raw, "metadata": manifest})
                running.records_inserted, running.records_updated = counts[:2]
                running.records_rejected = rejected
            except BaseException as exc:
                raw.processing_status = "quarantined"
                raw.save(update_fields=["processing_status"])
                issue(source, "ohlcv", "schema_or_file_failure", f"raw={raw.pk}: {type(exc).__name__}")
                raise
        return running

