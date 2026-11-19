from datetime import datetime, time, timedelta, timezone
import tempfile

from django.db import DatabaseError, connection
from django.db.models import DateTimeField
from django.db.models import Max
from django.http import FileResponse, StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, serializers, views
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from marketdata import models
from marketdata.exports import DATASETS, csv_chunks, write_parquet


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DataSource
        fields = "__all__"


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Instrument
        fields = "__all__"


class CotSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CotReport
        fields = "__all__"


class StatisticSerializer(serializers.ModelSerializer):
    source_published_at = serializers.DateTimeField(source="source_file.source_published_at", read_only=True)
    class Meta:
        model = models.FuturesDailyStatistic
        fields = "__all__"


class OhlcvSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.OhlcvBar
        fields = "__all__"


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CollectorJob
        fields = "__all__"


class QualitySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DataQualityIssue
        fields = "__all__"


class DatasetSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DatasetRegistry
        fields = "__all__"


class FilterQuery(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    source = serializers.CharField(required=False, max_length=40)
    instrument = serializers.IntegerField(required=False, min_value=1)
    exchange = serializers.CharField(required=False, max_length=40)
    symbol = serializers.CharField(required=False, max_length=100)
    asset_class = serializers.CharField(required=False, max_length=40)
    market_code = serializers.CharField(required=False, max_length=40)
    report_type = serializers.ChoiceField(required=False, choices=["legacy", "disaggregated", "tff"])
    futures_options_scope = serializers.ChoiceField(required=False, choices=["futures_only", "combined"])
    timeframe = serializers.CharField(required=False, max_length=20)
    price_type = serializers.CharField(required=False, max_length=30)
    report_status = serializers.ChoiceField(required=False, choices=["preliminary", "final", "unspecified"])
    severity = serializers.ChoiceField(required=False, choices=["INFO", "WARNING", "ERROR", "CRITICAL"])
    status = serializers.CharField(required=False, max_length=30)
    resolution_status = serializers.CharField(required=False, max_length=20)

    def validate(self, attrs):
        if attrs.get("start") and attrs.get("end") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("start must be on or before end")
        return attrs


def apply_filters(query, params, mapping, date_field=None):
    validator = FilterQuery(data=params)
    validator.is_valid(raise_exception=True)
    values = validator.validated_data
    for param, field in mapping.items():
        if param in values:
            query = query.filter(**{field: values[param]})
    if date_field:
        is_datetime = isinstance(query.model._meta.get_field(date_field), DateTimeField)
        if "start" in values:
            start = datetime.combine(values["start"], time.min, timezone.utc) if is_datetime else values["start"]
            query = query.filter(**{date_field + "__gte": start})
        if "end" in values:
            if is_datetime:
                if values["end"].year == 9999:
                    raise ValidationError({"end": "Date exceeds supported exclusive upper bound"})
                end = datetime.combine(values["end"] + timedelta(days=1), time.min, timezone.utc)
                query = query.filter(**{date_field + "__lt": end})
            else:
                query = query.filter(**{date_field + "__lte": values["end"]})
    return query


@extend_schema(parameters=[FilterQuery])
class FilteredList(generics.ListAPIView):
    filters = {}
    date_field = None

    def get_queryset(self):
        return apply_filters(super().get_queryset(), self.request.query_params, self.filters, self.date_field)


class SourceList(FilteredList):
    serializer_class = SourceSerializer
    queryset = models.DataSource.objects.order_by("name")


class InstrumentList(FilteredList):
    serializer_class = InstrumentSerializer
    queryset = models.Instrument.objects.order_by("id")
    filters = {k: k for k in ("exchange", "asset_class", "symbol")}


class CotList(FilteredList):
    serializer_class = CotSerializer
    queryset = models.CotReport.objects.order_by("-report_date", "id")
    filters = {k: k for k in ("market_code", "report_type", "futures_options_scope")}
    filters["source"] = "source__name"
    date_field = "report_date"


class OpenInterestList(FilteredList):
    serializer_class = StatisticSerializer
    queryset = models.FuturesDailyStatistic.objects.select_related("source_file").order_by("-trading_date", "id")
    filters = {"source": "source__name", "instrument": "instrument_id", "exchange": "instrument__exchange",
               "symbol": "instrument__symbol", "report_status": "report_status"}
    date_field = "trading_date"


class OhlcvList(FilteredList):
    serializer_class = OhlcvSerializer
    queryset = models.OhlcvBar.objects.order_by("-timestamp_utc", "id")
    filters = {"source": "source__name", "instrument": "instrument_id", "exchange": "instrument__exchange",
               "symbol": "instrument__symbol", "timeframe": "timeframe", "price_type": "price_type"}
    date_field = "timestamp_utc"


class JobList(FilteredList):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = JobSerializer
    queryset = models.CollectorJob.objects.order_by("-started_at", "id")
    filters = {"source": "source__name", "status": "status"}
    date_field = "started_at"


class QualityList(FilteredList):
    serializer_class = QualitySerializer
    queryset = models.DataQualityIssue.objects.order_by("-detected_at", "id")
    filters = {"source": "source__name", "severity": "severity", "resolution_status": "resolution_status"}
    date_field = "detected_at"


class DatasetList(FilteredList):
    serializer_class = DatasetSerializer
    queryset = models.DatasetRegistry.objects.order_by("id")


class Health(views.APIView):
    @extend_schema(responses={200: dict, 503: dict})
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                ready = cursor.fetchone() == (1,)
        except DatabaseError:
            ready = False
        return Response({"status": "ok" if ready else "unavailable", "database": "ready" if ready else "unavailable"},
                        status=200 if ready else 503)


class Overview(views.APIView):
    @extend_schema(responses={200: dict})
    def get(self, request):
        counts = {"cot": models.CotReport.objects.count(), "statistics": models.FuturesDailyStatistic.objects.count(),
                  "ohlcv": models.OhlcvBar.objects.count()}
        latest = [models.CotReport.objects.aggregate(d=Max("report_date"))["d"],
                  models.FuturesDailyStatistic.objects.aggregate(d=Max("trading_date"))["d"],
                  models.OhlcvBar.objects.aggregate(d=Max("timestamp_utc"))["d"]]
        dates = [v.isoformat() for v in latest if v is not None]
        return Response({"total_sources": models.DataSource.objects.count(),
            "active_sources": models.DataSource.objects.filter(enabled=True).count(),
            "total_instruments": models.Instrument.objects.count(), "total_records": sum(counts.values()),
            "record_counts": counts, "latest_data_date": max(dates) if dates else None,
            "last_successful_sync": models.CollectorJob.objects.filter(status="success", job_type="sync").aggregate(d=Max("finished_at"))["d"],
            "failed_jobs": models.CollectorJob.objects.filter(status="failed").count()})


class Export(views.APIView):
    @extend_schema(parameters=[FilterQuery], responses={200: bytes})
    def get(self, request, dataset):
        if dataset not in DATASETS:
            raise ValidationError("Unknown export dataset")
        file_format = request.query_params.get("file_format", "csv")
        if file_format not in {"csv", "parquet"}:
            raise ValidationError("file_format must be csv or parquet")
        definition = {"cot": CotList, "open-interest": OpenInterestList, "ohlcv": OhlcvList, "instruments": InstrumentList}[dataset]
        query = apply_filters(DATASETS[dataset].objects.order_by("pk"), request.query_params, definition.filters, definition.date_field)
        if file_format == "csv":
            response = StreamingHttpResponse(csv_chunks(query), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{dataset}.csv"'
            return response
        handle = tempfile.TemporaryFile()
        try:
            write_parquet(query, handle)
            handle.seek(0)
            return FileResponse(handle, as_attachment=True, filename=f"{dataset}.parquet", content_type="application/vnd.apache.parquet")
        except BaseException:
            handle.close()
            raise


class ActionQuery(serializers.Serializer):
    source = serializers.CharField(max_length=40)
    action = serializers.ChoiceField(choices=["enable", "disable", "sync", "backfill", "cancel"])
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    report_type = serializers.ChoiceField(required=False, choices=["legacy", "disaggregated", "tff"])
    scope = serializers.ChoiceField(required=False, choices=["futures_only", "combined"])
    market_code = serializers.CharField(required=False, max_length=40, allow_blank=True)

    def validate(self, attrs):
        if not models.DataSource.objects.filter(name=attrs["source"]).exists():
            raise serializers.ValidationError("Unknown source; run list_data_sources first")
        if attrs["action"] == "backfill" and (not attrs.get("start") or not attrs.get("end")):
            raise serializers.ValidationError("Backfill requires start and end")
        if attrs.get("start") and attrs.get("end") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("Invalid date range")
        if attrs["source"] != "cftc" and any(attrs.get(k) for k in ("report_type", "scope", "market_code")):
            raise serializers.ValidationError("COT filters are supported only for CFTC")
        return attrs


class CollectorAction(views.APIView):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=ActionQuery, responses={202: dict})
    def post(self, request):
        from marketdata.dashboard import perform_action
        from marketdata.collectors.base import CollectorError
        validator = ActionQuery(data=request.data)
        validator.is_valid(raise_exception=True)
        try:
            result = perform_action(validator.validated_data)
        except CollectorError as exc:
            raise ValidationError(str(exc)) from None
        return Response(result, status=202)

