"""Conservative quality monitoring: detect gaps, never fill them."""
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from marketdata import models


def scan_quality(source=None):
    sources = models.DataSource.objects.filter(pk=source.pk) if source else models.DataSource.objects.all()
    before = models.DataQualityIssue.objects.count()
    now = timezone.now()
    pending = []
    known = set()

    def flush():
        models.DataQualityIssue.objects.bulk_create(pending, batch_size=500)
        pending.clear()

    def issue(provider, dataset, kind, description, severity="ERROR"):
        description = description[:2000]
        identity = dataset, kind, description
        if identity in known:
            return
        known.add(identity)
        pending.append(models.DataQualityIssue(source=provider, dataset=dataset, issue_type=kind,
            description=description, severity=severity))
        if len(pending) >= 500:
            flush()

    for provider in sources:
        if not provider.enabled:
            continue
        known = set(models.DataQualityIssue.objects.filter(source=provider, resolution_status="open").values_list("dataset", "issue_type", "description"))
        latest = models.CollectorJob.objects.filter(source=provider, status="success").aggregate(value=Max("finished_at"))["value"]
        allowed_days = 10 if provider.data_frequency == "weekly" else 4
        if provider.data_frequency not in {"manual", "periodic"} and (latest is None or now - latest > timedelta(days=allowed_days)):
            issue(provider, "source", "stale_source", f"No successful sync within {allowed_days} days", "WARNING")
        observed = (models.CotReport.objects.filter(source=provider).aggregate(d=Max("report_date"))["d"]
                    if provider.name == "cftc" else models.FuturesDailyStatistic.objects.filter(source=provider).aggregate(d=Max("trading_date"))["d"])
        if provider.data_frequency in {"daily", "weekly"}:
            if observed is None:
                issue(provider, "source", "missing_dataset", "Enabled source has no observed market records", "WARNING")
            elif (now.date() - observed).days > allowed_days:
                issue(provider, "source", "stale_observation", f"Latest observed date {observed}; threshold {allowed_days} days", "WARNING")
        for raw in models.RawDataFile.objects.filter(source=provider, processing_status__in=["failed", "partial", "quarantined"]):
            issue(provider, "raw", "quarantined_file", f"raw={raw.pk} status={raw.processing_status}")
        for mapping in models.SourceInstrumentMapping.objects.filter(source=provider).select_related("instrument"):
            if mapping.valid_from and mapping.valid_to and mapping.valid_to < mapping.valid_from:
                issue(provider, "mapping", "invalid_mapping_range", f"mapping={mapping.pk}")
            if mapping.verification_status != "verified":
                issue(provider, "mapping", "unverified_mapping", f"mapping={mapping.pk}", "WARNING")
            if provider.name == "dukascopy" and mapping.instrument.contract_type != "fx_spot":
                issue(provider, "mapping", "cross_asset_mapping", f"mapping={mapping.pk}", "CRITICAL")
        for group in models.Instrument.objects.values("exchange", "symbol", "expiration_date").annotate(n=Count("id")).filter(n__gt=1):
            issue(provider, "instrument", "duplicate_identity", f"Duplicate instrument identity: {group['exchange']} {group['symbol']}")
        # Weekly COT coverage is observed within each market/type/scope; old semi-monthly series excluded.
        reports = models.CotReport.objects.filter(source=provider, report_date__gte="1992-10-01").order_by("market_code", "report_type", "futures_options_scope", "report_date").values_list("market_code", "report_type", "futures_options_scope", "report_date", "open_interest", "publication_date")
        previous_key = previous_date = None
        for code, kind, scope, report_date, oi, published in reports.iterator(chunk_size=2000):
            key = code, kind, scope
            if key == previous_key and (report_date - previous_date).days > 10:
                issue(provider, "cot", "historical_gap", f"{key}: {previous_date} to {report_date}; possible reporting gap", "WARNING")
            if oi is None or oi < 0:
                issue(provider, "cot", "invalid_value", f"{key} {report_date}: invalid open interest")
            if published and (published - report_date).days > 7:
                issue(provider, "cot", "publication_lag", f"{key} {report_date}: publication {published}", "WARNING")
            previous_key, previous_date = key, report_date
        for stat in models.FuturesDailyStatistic.objects.filter(source=provider).only("id", "volume", "open_interest").iterator():
            if stat.volume is not None and stat.volume < 0 or stat.open_interest is not None and stat.open_interest < 0:
                issue(provider, "daily_statistics", "invalid_value", f"statistic={stat.pk}")
        # Intraday gaps are only certified when a manifest declares an expected cadence and UTC session.
        for bar in models.OhlcvBar.objects.filter(source=provider).only("id", "open", "high", "low", "close", "volume").iterator():
            if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close) or bar.volume is not None and bar.volume < 0:
                issue(provider, "ohlcv", "invalid_value", f"bar={bar.pk}")
        flush()
    return models.DataQualityIssue.objects.count() - before

