import csv
import io
import re
import zipfile
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from django.db import transaction
from django.utils import timezone

from marketdata.collectors.base import BaseCollector, CollectorError
from marketdata.models import CollectorCheckpoint, CotReport, DataSource, QuarantinedRecord
from marketdata.runtime import check_cancel, fingerprint, issue, job_run, store_raw

INDEX_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm"
ARCHIVES = {
    "fut_disagg_txt": ("disaggregated", "futures_only"),
    "com_disagg_txt": ("disaggregated", "combined"),
    "fut_fin_txt": ("tff", "futures_only"),
    "com_fin_txt": ("tff", "combined"),
    "deacot": ("legacy", "futures_only"),
    "deahistfo": ("legacy", "combined"),
}
REQUIRED = {"market_and_exchange_names", "as_of_date_in_form_yymmdd", "cftc_contract_market_code", "open_interest_all"}


def archive_details(url):
    name = Path(urlparse(url).path).name.lower()
    for prefix, (report_type, scope) in ARCHIVES.items():
        match = re.fullmatch(rf"{prefix}_?(\d{{4}})\.zip", name)
        if match:
            return int(match.group(1)), report_type, scope
    return None


def clean_key(key):
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def parse_date(value):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%y%m%d", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise CollectorError("Invalid COT date")


def parse_integer(value):
    text = value.strip().replace(",", "")
    if not text:
        return None
    if not re.fullmatch(r"[+-]?\d+", text):
        raise CollectorError("Invalid nonnegative COT integer")
    result = int(text)
    if result < 0:
        raise CollectorError("Negative COT position or open interest")
    if result > 9223372036854775807:
        raise CollectorError("COT integer exceeds database range")
    return result


class CftcCollector(BaseCollector):
    allowed_host = "www.cftc.gov"

    def discover(self):
        class Links(HTMLParser):
            urls = None

            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    url = urljoin(INDEX_URL, dict(attrs).get("href", ""))
                    if archive_details(url):
                        self.urls.append(url)

        parser = Links()
        parser.feed(self.fetch(INDEX_URL).decode("utf-8", errors="strict"))
        urls = []
        for url in sorted(set(parser.urls)):
            self._check_url(url)
            urls.append(url)
        return urls

    def download(self, url):
        # Compatibility with the public bytes API; production uses disk-spilled streams.
        return self.fetch_file(url)

    def parse(self, content):
        handle = io.BytesIO(content) if isinstance(content, bytes) else content
        try:
            archive = zipfile.ZipFile(handle)
        except (zipfile.BadZipFile, OSError):
            raise CollectorError("Invalid CFTC ZIP") from None
        try:
            with archive:
                members = [m for m in archive.infolist() if m.filename.lower().endswith((".txt", ".csv")) and not m.is_dir()]
                if not members or len(members) > 5:
                    raise CollectorError("Unexpected CFTC archive members")
                if sum(m.file_size for m in members) > 500 * 1024 * 1024:
                    raise CollectorError("CFTC archive exceeds extraction limit")
                for member in members:
                    if member.flag_bits & 1 or member.compress_size == 0 or member.file_size / member.compress_size > 200:
                        raise CollectorError("Unsafe CFTC archive compression")
                    # Detect encoding with a bounded-memory pass before yielding any rows.
                    encoding = "utf-8-sig"
                    try:
                        with archive.open(member) as binary, io.TextIOWrapper(binary, encoding=encoding) as text:
                            while text.read(64 * 1024):
                                pass
                    except UnicodeDecodeError:
                        encoding = "cp1252"
                    with archive.open(member) as binary, io.TextIOWrapper(binary, encoding=encoding, newline="") as text:
                        reader = csv.reader(text, strict=True)
                        header = next(reader, None)
                        if not header:
                            raise CollectorError("CFTC archive has no CSV header")
                        keys = [clean_key(k) for k in header]
                        if len(set(keys)) != len(keys) or any(not k for k in keys):
                            raise CollectorError("Duplicate or blank CFTC CSV header")
                        if not REQUIRED.issubset(keys):
                            raise CollectorError(f"Missing CFTC columns: {sorted(REQUIRED - set(keys))}")
                        for values in reader:
                            if not values:
                                continue
                            if len(values) != len(keys):
                                raise CollectorError("Unexpected CFTC CSV row width")
                            yield dict(zip(keys, (value.strip() for value in values)))
        except (zipfile.BadZipFile, RuntimeError, UnicodeError, csv.Error, EOFError, NotImplementedError):
            raise CollectorError("Invalid CFTC ZIP or CSV structure") from None

    def validate(self, row):
        missing = REQUIRED - row.keys()
        if missing:
            raise CollectorError(f"Missing CFTC columns: {sorted(missing)}")
        if not re.fullmatch(r"[A-Za-z0-9+.-]{1,40}", row["cftc_contract_market_code"]):
            raise CollectorError("Missing or invalid CFTC market code")
        if not row["market_and_exchange_names"]:
            raise CollectorError("Missing CFTC market name")

    def normalize(self, row, report_type, scope):
        self.validate(row)
        if (report_type, scope) not in ARCHIVES.values():
            raise CollectorError("Unknown COT report type or scope")
        family_fields = {"legacy": {"noncommercial_positions_long_all", "noncomm_positions_long_all"},
                         "disaggregated": {"m_money_positions_long_all"}, "tff": {"dealer_positions_long_all"}}
        if not family_fields[report_type].intersection(row):
            raise CollectorError("COT schema does not match the archive report family")
        declared_scope = row.get("futonly_or_combined")
        if declared_scope and declared_scope != {"futures_only": "FutOnly", "combined": "Combined"}[scope]:
            raise CollectorError("COT row scope contradicts archive scope")
        positions = {}
        for key, value in row.items():
            # Includes Legacy Comm/NonComm/NonRept names and all actual position fields.
            if ("positions_" in key or key.startswith("nonrept_")) and key.endswith(("_long_all", "_short_all", "_spreading_all", "_spread_all")):
                positions[key] = parse_integer(value)
                if positions[key] is None:
                    raise CollectorError("Missing COT position; refusing to overwrite verified values")
        oi = parse_integer(row["open_interest_all"])
        if oi is None:
            raise CollectorError("Missing COT open interest")
        report_date = parse_date(row["as_of_date_in_form_yymmdd"])
        for key in ("report_date_as_yyyy_mm_dd", "as_of_date_in_form_yyyy_mm_dd"):
            if row.get(key) and parse_date(row[key]) != report_date:
                raise CollectorError("COT reporting date columns disagree")
        if report_date > timezone.now().date():
            raise CollectorError("COT reporting date is in the future")
        return {
            "report_date": report_date, "market_code": row["cftc_contract_market_code"],
            "market_name": row["market_and_exchange_names"][:255],
            "report_type": report_type, "futures_options_scope": scope, "open_interest": oi,
            "trader_positions": positions, "raw_fields": row,
        }

    def persist(self, rows, source_file):
        """Bounded bulk upsert; caller's file transaction includes checkpoint and quarantine."""
        inserted = updated = 0
        batch = []
        seen = {}
        duplicates = 0
        unique = ["source", "report_date", "market_code", "report_type", "futures_options_scope"]
        fields = ["market_name", "open_interest", "trader_positions", "raw_fields", "source_file", "updated_at"]

        def flush(batch):
            if not batch:
                return 0, 0
            # Remove repeated identical keys in a batch: PostgreSQL ON CONFLICT cannot affect a row twice.
            keyed = {}
            for row in batch:
                key = tuple(row[k] for k in unique[1:])
                if key in keyed and keyed[key] != row:
                    raise CollectorError("Conflicting duplicate COT identity within a file")
                keyed[key] = row
            existing = set(CotReport.objects.filter(source=source_file.source,
                report_date__in={r["report_date"] for r in keyed.values()},
                market_code__in={r["market_code"] for r in keyed.values()},
                report_type__in={r["report_type"] for r in keyed.values()},
                futures_options_scope__in={r["futures_options_scope"] for r in keyed.values()}
                ).values_list(*unique[1:]))
            objects = [CotReport(source=source_file.source, source_file=source_file, **r) for r in keyed.values()]
            CotReport.objects.bulk_create(objects, batch_size=500, update_conflicts=True,
                unique_fields=unique, update_fields=fields)
            changed = len(set(keyed) & existing)
            return len(keyed) - changed, changed

        with transaction.atomic():
            for row in rows:
                identity = tuple(row[k] for k in unique[1:])
                digest = fingerprint(row)
                if identity in seen:
                    if seen[identity] != digest:
                        raise CollectorError("Conflicting duplicate COT identity across file batches")
                    duplicates += 1
                    continue
                seen[identity] = digest
                batch.append(row)
                if len(batch) == 500:
                    added, changed = flush(batch)
                    inserted += added
                    updated += changed
                    batch.clear()
            added, changed = flush(batch)
            if duplicates:
                issue(source_file.source, "cot", "duplicate_records", f"raw={source_file.pk}: {duplicates} identical duplicate rows skipped", "INFO")
        return inserted + added, updated + changed, 0

    def _run(self, start, end, job_type, report_type=None, scope=None, market_code=None, job=None):
        if start > end:
            raise CollectorError("Start date is after end date")
        if report_type is not None and report_type not in {"legacy", "disaggregated", "tff"}:
            raise CollectorError("Invalid report_type")
        if scope is not None and scope not in {"futures_only", "combined"}:
            raise CollectorError("Invalid scope")
        source = DataSource.objects.get(name="cftc")
        params = {"start": str(start), "end": str(end), "report_type": report_type, "scope": scope, "market_code": market_code}
        with job_run(source, job_type, params, job, transport=self) as running:
            urls = [u for u in self.discover() if start.year <= archive_details(u)[0] <= end.year
                    and (report_type is None or archive_details(u)[1] == report_type)
                    and (scope is None or archive_details(u)[2] == scope)]
            if not urls:
                raise CollectorError("No CFTC archives found for requested filters")
            for url in urls:
                check_cancel(running)
                _, kind, archive_scope = archive_details(url)
                content = self.download(url)
                try:
                    raw = store_raw(source, content, url, Path(urlparse(url).path).name, "zip")
                finally:
                    if hasattr(content, "close"):
                        content.close()
                running.records_downloaded += 1  # Number of raw files, explicitly documented.
                coverage = params if job_type == "backfill" else {"mode": "sync", "report_type": report_type, "scope": scope, "market_code": market_code}
                key = fingerprint({"url": url, **coverage})
                previous = CollectorCheckpoint.objects.filter(source=source, key=key).first()
                if previous and previous.raw_file_id == raw.pk:
                    continue
                raw.processing_status = "processing"
                raw.save(update_fields=["processing_status"])
                rejected = 0
                try:
                    with transaction.atomic():
                        def selected_rows():
                            nonlocal rejected
                            with open(raw.storage_path, "rb") as handle:
                                for number, row in enumerate(self.parse(handle), 2):
                                    if number % 500 == 0:
                                        check_cancel(running)
                                    try:
                                        normalized = self.normalize(row, kind, archive_scope)
                                    except CollectorError as exc:
                                        rejected += 1
                                        QuarantinedRecord.objects.update_or_create(source_file=raw, row_number=number,
                                            defaults={"payload": row, "reason": str(exc)[:1000]})
                                        issue(source, "cot", "invalid_record", f"raw={raw.pk} row={number}: {exc}")
                                        continue
                                    if start <= normalized["report_date"] <= end and (not market_code or normalized["market_code"] == market_code):
                                        yield normalized
                        inserted, updated, _ = self.persist(selected_rows(), raw)
                        if previous and previous.raw_file_id != raw.pk:
                            issue(source, "cot", "source_revision", f"Checkpoint {key} revised: old_raw={previous.raw_file_id} new_raw={raw.pk}", "INFO")
                        if rejected == 0:
                            CollectorCheckpoint.objects.update_or_create(source=source, key=key,
                                defaults={"raw_file": raw, "metadata": params})
                        raw.processing_status = "partial" if rejected else "complete"
                        raw.save(update_fields=["processing_status"])
                    running.records_inserted += inserted
                    running.records_updated += updated
                    running.records_rejected += rejected
                    running.retry_count = max(running.retry_count, self.retry_count)
                    running.save(update_fields=["records_downloaded", "records_inserted", "records_updated", "records_rejected", "retry_count"])
                except BaseException as exc:
                    raw.processing_status = "failed"
                    raw.save(update_fields=["processing_status"])
                    issue(source, "cot", "file_failure", f"raw={raw.pk}: {type(exc).__name__}")
                    raise
        return running

    def sync(self, report_type=None, scope=None, market_code=None, job=None):
        # Revisit last year as well: New Year releases and late revisions can touch it.
        today = timezone.now().date()
        return self._run(date(today.year - 1, 1, 1), today, "sync", report_type, scope, market_code, job)

    def backfill(self, start, end, report_type=None, scope=None, market_code=None, job=None):
        return self._run(start, end, "backfill", report_type, scope, market_code, job)

