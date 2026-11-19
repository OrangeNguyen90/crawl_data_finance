from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Max
from django.shortcuts import redirect, render
from django.contrib import messages
from django.views.decorators.http import require_POST

from marketdata import models
from marketdata.collectors.base import CollectorError
from marketdata.jobs import enqueue
from marketdata.views import ActionQuery


@staff_member_required
def dashboard(request):
    counts = {"COT": models.CotReport.objects.count(), "Daily statistics": models.FuturesDailyStatistic.objects.count(),
              "OHLCV": models.OhlcvBar.objects.count()}
    latest = [models.CotReport.objects.aggregate(d=Max("report_date"))["d"],
              models.FuturesDailyStatistic.objects.aggregate(d=Max("trading_date"))["d"],
              models.OhlcvBar.objects.aggregate(d=Max("timestamp_utc"))["d"]]
    dates = [v.isoformat() for v in latest if v is not None]
    context = {"counts": counts, "total_records": sum(counts.values()),
        "total_sources": models.DataSource.objects.count(), "active_sources": models.DataSource.objects.filter(enabled=True).count(),
        "instruments": models.Instrument.objects.count(), "latest_date": max(dates) if dates else None,
        "last_sync": models.CollectorJob.objects.filter(status="success", job_type="sync").aggregate(d=Max("finished_at"))["d"],
        "failed_jobs": models.CollectorJob.objects.filter(status="failed").count(),
        "sources": models.DataSource.objects.order_by("name"), "jobs": models.CollectorJob.objects.select_related("source").order_by("-id")[:30],
        "issues": models.DataQualityIssue.objects.select_related("source").filter(resolution_status="open").order_by("-detected_at")[:30],
        "coverage": models.CotReport.objects.values("source__name", "report_type", "futures_options_scope").annotate(records=Count("id"), latest=Max("report_date")),
        "stats": models.FuturesDailyStatistic.objects.select_related("instrument", "source").order_by("-trading_date", "id")[:20],
        "cot": models.CotReport.objects.order_by("-report_date", "id")[:20],
        "bars": models.OhlcvBar.objects.select_related("instrument", "source").order_by("-timestamp_utc", "id")[:20],
        "metadata": models.Instrument.objects.order_by("id")[:20]}
    return render(request, "marketdata/dashboard.html", context)


@staff_member_required
@require_POST
def action(request):
    serializer = ActionQuery(data=request.POST)
    if not serializer.is_valid():
        messages.error(request, str(serializer.errors))
        return redirect("dashboard")
    try:
        perform_action(serializer.validated_data)
        messages.success(request, "Action recorded. Queued jobs run when the collector worker ticks.")
    except CollectorError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard")


def perform_action(data):
    source = models.DataSource.objects.get(name=data["source"])
    operation = data["action"]
    if operation in {"enable", "disable"}:
        source.enabled = operation == "enable"
        source.save(update_fields=["enabled", "updated_at"])
        if operation == "disable":
            models.CollectorJob.objects.filter(source=source, status__in=["queued", "claimed", "running"]).update(cancel_requested=True)
        return {"source": source.name, "enabled": source.enabled}
    if operation == "cancel":
        count = models.CollectorJob.objects.filter(source=source, status__in=["queued", "claimed", "running"]).update(cancel_requested=True)
        return {"cancel_requested": count}
    params = {k: str(data[k]) for k in ("start", "end", "report_type", "scope", "market_code") if data.get(k)}
    job = enqueue(source, operation, params)
    return {"job_id": job.pk, "status": job.status}

