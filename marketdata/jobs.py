"""Database queue driven by one Windows Task Scheduler entry; no background web threads."""
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from marketdata.collectors.base import CollectorError
from marketdata.collectors.registry import get_collector
from marketdata.models import CollectorJob, CollectorLock, DataSource, SourceSchedule

ACTIVE = ["queued", "claimed", "running"]


def enqueue(source, kind="sync", parameters=None, attempt_number=0):
    if source.name in {"dukascopy", "firstrate"}:
        raise CollectorError("Manual import sources cannot be queued for remote sync")
    if kind == "backfill" and source.name != "cftc":
        raise CollectorError("Historical discovery is currently verified only for CFTC")
    if not source.enabled:
        raise CollectorError("Source is disabled")
    with transaction.atomic():
        DataSource.objects.select_for_update().get(pk=source.pk)
        if CollectorJob.objects.filter(source=source, status__in=ACTIVE).exists() or CollectorLock.objects.filter(source=source).exists():
            raise CollectorError("Source already has active work")
        return CollectorJob.objects.create(source=source, job_type=kind, status="queued",
            parameters=parameters or {}, attempt_number=attempt_number)


def schedule_due():
    now = timezone.now()
    for pk in SourceSchedule.objects.filter(enabled=True, source__enabled=True, next_run_at__lte=now).values_list("pk", flat=True):
        with transaction.atomic():
            schedule = SourceSchedule.objects.select_for_update().select_related("source").get(pk=pk)
            if schedule.next_run_at > now or schedule.interval_minutes < 1:
                continue
            try:
                enqueue(schedule.source)
            except CollectorError:
                continue
            schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
            schedule.save(update_fields=["next_run_at"])


def execute_next():
    candidate = CollectorJob.objects.filter(status="queued").order_by("id").first()
    if candidate is None:
        return None
    claimed = CollectorJob.objects.filter(pk=candidate.pk, status="queued").update(status="claimed", heartbeat_at=timezone.now())
    if not claimed:
        return None
    candidate.refresh_from_db()
    collector = get_collector(candidate.source.name)
    try:
        if candidate.cancel_requested:
            candidate.status = "cancelled"
            candidate.finished_at = timezone.now()
            candidate.save()
            return candidate
        params = {k: v for k, v in candidate.parameters.items() if v is not None}
        if candidate.job_type == "backfill":
            collector.backfill(date.fromisoformat(params.pop("start")), date.fromisoformat(params.pop("end")), job=candidate, **params)
        else:
            params.pop("start", None)
            params.pop("end", None)
            collector.sync(job=candidate, **params)
    except Exception as exc:
        candidate.refresh_from_db()
        if candidate.status == "claimed":
            # Failure before job_run (disabled source, configuration, source lock).
            candidate.status = "failed"
            candidate.finished_at = timezone.now()
            candidate.error_message = str(exc) if isinstance(exc, CollectorError) else f"{type(exc).__name__}; details suppressed"
            candidate.save()
    finally:
        collector.close()
    candidate.refresh_from_db()
    return candidate


def retry_failed():
    # Only the latest attempt for each source; pending jobs block additional retries.
    for source in DataSource.objects.filter(enabled=True):
        schedule = SourceSchedule.objects.filter(source=source, enabled=True).first()
        if not schedule:
            continue
        latest = CollectorJob.objects.filter(source=source).order_by("-id").first()
        if latest and latest.status == "failed" and latest.attempt_number < schedule.max_retries:
            if latest.finished_at and timezone.now() - latest.finished_at < timedelta(minutes=2 ** latest.attempt_number):
                continue
            try:
                enqueue(source, latest.job_type, latest.parameters, latest.attempt_number + 1)
            except CollectorError:
                pass

