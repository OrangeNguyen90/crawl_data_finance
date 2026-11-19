import uuid
from datetime import date
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone

from marketdata.collectors.base import CollectorCancelled, CollectorError
from marketdata.collectors.cftc import CftcCollector
from marketdata.jobs import enqueue, execute_next, schedule_due
from marketdata.models import CollectorJob, CollectorLock, DataSource, SourceSchedule
from marketdata.runtime import check_cancel, job_run


@pytest.fixture
def source(db):
    return DataSource.objects.create(name="cftc", enabled=True, provider_type="cot")


def test_mutex_prevents_concurrent_run(source):
    with job_run(source, "sync"):
        with pytest.raises(CollectorError, match="locked"):
            with job_run(source, "sync"):
                pass
    assert not CollectorLock.objects.exists()


def test_job_cancel_at_safe_boundary(source):
    with pytest.raises(CollectorCancelled):
        with job_run(source, "sync") as job:
            CollectorJob.objects.filter(pk=job.pk).update(cancel_requested=True)
            check_cancel(job)
    job.refresh_from_db()
    assert job.status == "cancelled" and job.cancel_requested
    assert not CollectorLock.objects.exists()


def test_queued_job_claim_and_completion(source):
    queued = enqueue(source)
    with patch.object(CftcCollector, "sync", autospec=True) as sync:
        def run(collector, job):
            with job_run(source, "sync", job=job) as j:
                j.records_inserted = 7
        sync.side_effect = run
        result = execute_next()
    assert result.pk == queued.pk and result.status == "success" and result.records_inserted == 7


def test_queue_rejects_duplicate_work(source):
    enqueue(source)
    with pytest.raises(CollectorError, match="active"):
        enqueue(source)


def test_scheduler_does_not_duplicate_due_work(source):
    SourceSchedule.objects.create(source=source, enabled=True, next_run_at=timezone.now())
    schedule_due()
    schedule_due()
    assert CollectorJob.objects.count() == 1


def test_cancelled_queue_never_calls_collector(source):
    job = enqueue(source)
    job.cancel_requested = True
    job.save()
    with patch.object(CftcCollector, "sync") as sync:
        result = execute_next()
    assert result.status == "cancelled"
    sync.assert_not_called()


class Response:
    def __init__(self, status=200, chunks=None):
        self.status_code = status
        self.headers = {}
        self.chunks = chunks or [b"data"]
        self.closed = False

    def iter_content(self, size):
        yield from self.chunks

    def close(self):
        self.closed = True


@pytest.mark.parametrize("url", ["https://www.cftc.gov:444/file", "https://user:pass@www.cftc.gov/file", "https://www.cftc.gov:bad/file", "https://www.cftc.gov.evil/file"])
def test_url_validation_rejects_ports_and_credentials(url):
    with pytest.raises(CollectorError):
        CftcCollector()._check_url(url)


def test_stream_limits_and_closes_response():
    response = Response(chunks=[b"x" * 10])
    c = CftcCollector()
    c.max_bytes = 5
    with patch.object(c.session, "get", return_value=response), pytest.raises(CollectorError, match="limit"):
        c.fetch("https://www.cftc.gov/file")
    assert response.closed


def test_retries_are_bounded_and_responses_closed():
    responses = [Response(503), Response(429), Response(200)]
    c = CftcCollector()
    with patch.object(c.session, "get", side_effect=responses), patch("marketdata.collectors.base.time.sleep"):
        assert c.fetch("https://www.cftc.gov/file") == b"data"
    assert c.retry_count == 2 and all(r.closed for r in responses)


def test_redirect_is_not_followed():
    c = CftcCollector()
    with patch.object(c.session, "get", return_value=Response(302)) as get, pytest.raises(CollectorError):
        c.fetch("https://www.cftc.gov/file")
    assert get.call_args.kwargs["allow_redirects"] is False

