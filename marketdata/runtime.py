"""Durable source mutex, atomic raw storage and job lifecycle."""
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from marketdata.collectors.base import CollectorCancelled, CollectorError
from marketdata.models import CollectorJob, CollectorLock, DataQualityIssue, RawDataFile

logger = logging.getLogger("marketdata")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def check_cancel(job):
    state = CollectorJob.objects.values("cancel_requested", "source__enabled").get(pk=job.pk)
    if state["cancel_requested"] or not state["source__enabled"]:
        raise CollectorCancelled("Job stopped at a safe checkpoint")
    # Updating the job inside a file transaction would block another connection's cancel request.
    if not connection.in_atomic_block:
        CollectorJob.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now())


@contextmanager
def job_run(source, kind, parameters=None, job=None, transport=None):
    if not source.enabled:
        raise CollectorError("Source is disabled; enable it explicitly before running")
    token = uuid.uuid4()
    try:
        with transaction.atomic():
            CollectorLock.objects.create(source=source, owner=token)
    except IntegrityError:
        raise CollectorError("Source already locked; inspect the owning worker before recovery") from None
    try:
        if job is None:
            job = CollectorJob.objects.create(source=source, job_type=kind, parameters=parameters or {})
        else:
            if job.source_id != source.pk or job.status not in {"queued", "claimed"}:
                raise CollectorError("Queued job cannot be claimed")
            job.status = "running"
            job.started_at = timezone.now()
            job.save(update_fields=["status", "started_at"])
        try:
            check_cancel(job)
            yield job
            job.status = "partial" if job.records_rejected else "success"
        except BaseException as exc:
            job.status = "cancelled" if isinstance(exc, CollectorCancelled) else "failed"
            job.error_message = str(exc)[:1000] if isinstance(exc, CollectorError) else f"{type(exc).__name__}; details suppressed"
            try:
                issue(source, "collector", "job_cancelled" if isinstance(exc, CollectorCancelled) else "collector_failure",
                    f"job={job.pk}: {job.error_message}", "INFO" if isinstance(exc, CollectorCancelled) else "ERROR")
            except DatabaseError:
                logger.error("quality_issue_write_failed", extra={"job_id": job.pk})
            raise
        finally:
            if transport is not None:
                job.retry_count = transport.retry_count
            job.finished_at = timezone.now()
            job.heartbeat_at = job.finished_at
            try:
                job.save(update_fields=["status", "finished_at", "heartbeat_at", "error_message",
                    "records_downloaded", "records_inserted", "records_updated", "records_rejected", "retry_count"])
            except DatabaseError:
                logger.error("job_state_write_failed", extra={"job_id": job.pk})
            logger.info("collector_finished", extra={"job_id": job.pk, "source_name": source.name, "job_status": job.status})
    finally:
        try:
            CollectorLock.objects.filter(source=source, owner=token).delete()
        except DatabaseError:
            logger.error("lock_release_failed", extra={"source_name": source.name})


def store_raw(source, content, url, name, file_format, metadata=None):
    """Atomic same-directory replace; never extract archive paths."""
    handle = io.BytesIO(content) if isinstance(content, bytes) else content
    handle.seek(0)
    digest = hashlib.sha256()
    size = 0
    root = Path(settings.MARKETDATA_RAW_ROOT) / source.name
    root.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="download-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "wb") as output:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
        sha = digest.hexdigest()
        path = root / f"{sha}.{file_format}"
        os.replace(temp, path)
        raw, _ = RawDataFile.objects.get_or_create(source=source, sha256=sha, defaults={
            "file_name": name[:255], "original_url": url, "file_format": file_format,
            "file_size": size, "storage_path": str(path), "metadata": metadata or {}})
        origins = raw.metadata.get("observed_urls", [raw.original_url])
        changed = []
        if url not in origins:
            raw.metadata = {**raw.metadata, "observed_urls": origins + [url]}
            changed.append("metadata")
        if raw.storage_path != str(path):
            raw.storage_path = str(path)
            changed.append("storage_path")
        if changed:
            raw.save(update_fields=changed)
        return raw
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def issue(source, dataset, kind, description, severity="ERROR", instrument=None):
    return DataQualityIssue.objects.get_or_create(source=source, dataset=dataset,
        issue_type=kind, description=description[:2000], resolution_status="open",
        defaults={"severity": severity, "instrument": instrument})[0]

