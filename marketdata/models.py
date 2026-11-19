from django.db import models
from django.utils import timezone


class DataSource(models.Model):
    name = models.CharField(max_length=40, unique=True)
    provider_type = models.CharField(max_length=40)
    official_url = models.URLField()
    access_method = models.CharField(max_length=40, default="public_http")
    data_frequency = models.CharField(max_length=40, blank=True)
    license_status = models.CharField(max_length=40, default="unverified")
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Instrument(models.Model):
    exchange = models.CharField(max_length=40)
    symbol = models.CharField(max_length=100)
    canonical_symbol = models.CharField(max_length=100, blank=True)
    instrument_name = models.CharField(max_length=255)
    asset_class = models.CharField(max_length=40, blank=True)
    contract_type = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=10, blank=True)
    contract_size = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    tick_size = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exchange", "symbol", "expiration_date"], name="unique_instrument_contract")]
        constraints += [models.UniqueConstraint(fields=["exchange", "symbol"], condition=models.Q(expiration_date__isnull=True), name="unique_undated_instrument")]
        indexes = [models.Index(fields=["exchange", "symbol"])]


class SourceInstrumentMapping(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    source_symbol = models.CharField(max_length=100)
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    mapping_type = models.CharField(max_length=40)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    verification_status = models.CharField(max_length=40, default="unverified")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "source_symbol", "instrument", "mapping_type"], name="unique_source_mapping")]


class RawDataFile(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    file_name = models.CharField(max_length=255)
    original_url = models.URLField(max_length=1000)
    file_format = models.CharField(max_length=20)
    sha256 = models.CharField(max_length=64, db_index=True)
    file_size = models.BigIntegerField()
    downloaded_at = models.DateTimeField(auto_now_add=True)
    source_published_at = models.DateTimeField(null=True, blank=True)
    storage_path = models.CharField(max_length=1000)
    processing_status = models.CharField(max_length=40, default="downloaded")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "sha256"], name="unique_source_raw_digest")]


class CotReport(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    report_date = models.DateField()
    publication_date = models.DateField(null=True, blank=True)
    market_code = models.CharField(max_length=40)
    market_name = models.CharField(max_length=255, blank=True)
    report_type = models.CharField(max_length=40)
    futures_options_scope = models.CharField(max_length=40)
    open_interest = models.BigIntegerField(null=True, blank=True)
    trader_positions = models.JSONField(default=dict)
    raw_fields = models.JSONField(default=dict)
    source_file = models.ForeignKey(RawDataFile, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "report_date", "market_code", "report_type", "futures_options_scope"], name="unique_cot_report")]
        indexes = [models.Index(fields=["report_date", "market_code"])]
        indexes += [models.Index(fields=["source", "market_code", "report_type", "futures_options_scope", "report_date"])]


class FuturesDailyStatistic(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    trading_date = models.DateField()
    volume = models.BigIntegerField(null=True, blank=True)
    open_interest = models.BigIntegerField(null=True, blank=True)
    change_in_oi = models.BigIntegerField(null=True, blank=True)
    report_status = models.CharField(max_length=20)
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    source_file = models.ForeignKey(RawDataFile, on_delete=models.PROTECT)
    raw_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "trading_date", "source", "report_status"], name="unique_daily_statistic")]
        indexes = [models.Index(fields=["source", "trading_date"])]


class OhlcvBar(models.Model):
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    timeframe = models.CharField(max_length=20)
    timestamp_utc = models.DateTimeField()
    open = models.DecimalField(max_digits=24, decimal_places=8)
    high = models.DecimalField(max_digits=24, decimal_places=8)
    low = models.DecimalField(max_digits=24, decimal_places=8)
    close = models.DecimalField(max_digits=24, decimal_places=8)
    volume = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    volume_type = models.CharField(max_length=30)
    price_type = models.CharField(max_length=30)
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    source_file = models.ForeignKey(RawDataFile, on_delete=models.PROTECT)
    raw_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "timeframe", "timestamp_utc", "price_type", "source"], name="unique_ohlcv_bar")]
        indexes = [models.Index(fields=["source", "timeframe", "timestamp_utc"])]


class CollectorJob(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    job_type = models.CharField(max_length=30)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, default="running")
    records_downloaded = models.PositiveIntegerField(default=0)
    records_inserted = models.PositiveIntegerField(default=0)
    records_updated = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    attempt_number = models.PositiveIntegerField(default=0)
    parameters = models.JSONField(default=dict, blank=True)
    cancel_requested = models.BooleanField(default=False)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["source", "started_at"])]
        indexes += [models.Index(fields=["status", "id"])]


class DataQualityIssue(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    dataset = models.CharField(max_length=60)
    instrument = models.ForeignKey(Instrument, null=True, blank=True, on_delete=models.PROTECT)
    issue_type = models.CharField(max_length=60)
    severity = models.CharField(max_length=20)
    detected_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField()
    resolution_status = models.CharField(max_length=20, default="open")

    class Meta:
        indexes = [models.Index(fields=["resolution_status", "detected_at"])]


class DatasetRegistry(models.Model):
    dataset_name = models.CharField(max_length=255)
    provider = models.CharField(max_length=100)
    original_publisher = models.CharField(max_length=100, blank=True)
    dataset_url = models.URLField(max_length=1000, unique=True)
    exchange_coverage = models.JSONField(default=list)
    instruments = models.JSONField(default=list)
    data_type = models.CharField(max_length=60, blank=True)
    frequency = models.CharField(max_length=40, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    last_updated = models.DateField(null=True, blank=True)
    license = models.CharField(max_length=255, blank=True)
    redistribution_permission = models.CharField(max_length=30, default="unverified")
    commercial_use_permission = models.CharField(max_length=30, default="unverified")
    data_provenance = models.TextField(blank=True)
    verification_status = models.CharField(max_length=30, default="unverified")


class CollectorLock(models.Model):
    """No automatic expiry: recovery must establish that the owner has stopped."""
    source = models.OneToOneField(DataSource, primary_key=True, on_delete=models.PROTECT)
    owner = models.UUIDField()
    acquired_at = models.DateTimeField(auto_now_add=True)


class CollectorCheckpoint(models.Model):
    source = models.ForeignKey(DataSource, on_delete=models.PROTECT)
    key = models.CharField(max_length=64)
    raw_file = models.ForeignKey(RawDataFile, on_delete=models.PROTECT)
    completed_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "key"], name="unique_collector_checkpoint")]


class QuarantinedRecord(models.Model):
    source_file = models.ForeignKey(RawDataFile, on_delete=models.PROTECT)
    row_number = models.PositiveIntegerField()
    payload = models.JSONField(default=dict)
    reason = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_file", "row_number"], name="unique_quarantined_row")]


class SourceSchedule(models.Model):
    source = models.OneToOneField(DataSource, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveIntegerField(default=1440)
    next_run_at = models.DateTimeField(default=timezone.now)
    max_retries = models.PositiveIntegerField(default=2)
