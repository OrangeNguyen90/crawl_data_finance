"""Bounded CSV/Parquet serialization shared by API and management command."""
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from itertools import islice

import pyarrow as pa
import pyarrow.parquet as pq
from django.db import models

from marketdata.models import CotReport, FuturesDailyStatistic, Instrument, OhlcvBar

DATASETS = {"cot": CotReport, "open-interest": FuturesDailyStatistic, "ohlcv": OhlcvBar, "instruments": Instrument}


def fields_for(model):
    return [f for f in model._meta.concrete_fields if f.name != "raw_fields"]


def schema_for(fields):
    result = []
    for field in fields:
        if isinstance(field, models.ForeignKey) or isinstance(field, (models.IntegerField, models.AutoField)):
            kind = pa.int64()
        elif isinstance(field, models.DecimalField):
            kind = pa.decimal128(field.max_digits, field.decimal_places)
        elif isinstance(field, models.DateTimeField):
            kind = pa.timestamp("us", tz="UTC")
        elif isinstance(field, models.DateField):
            kind = pa.date32()
        elif isinstance(field, models.BooleanField):
            kind = pa.bool_()
        else:
            kind = pa.string()
        result.append(pa.field(field.attname, kind, nullable=True))
    return pa.schema(result)


def csv_chunks(queryset):
    fields = fields_for(queryset.model)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([f.attname for f in fields])
    yield output.getvalue()
    for row in queryset.values_list(*(f.attname for f in fields)).iterator(chunk_size=2000):
        output.seek(0)
        output.truncate()
        # Prevent spreadsheet formulas in provider-controlled text; numeric cells stay numeric.
        cells = [json.dumps(value, sort_keys=True) if isinstance(field, models.JSONField) else value for field, value in zip(fields, row)]
        writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in cells])
        yield output.getvalue()


def write_parquet(queryset, destination):
    fields = fields_for(queryset.model)
    schema = schema_for(fields)
    rows = iter(queryset.values(*(f.attname for f in fields)).iterator(chunk_size=2000))
    with pq.ParquetWriter(destination, schema, compression="snappy") as writer:
        while batch := list(islice(rows, 2000)):
            for row in batch:
                for field in fields:
                    if isinstance(field, models.JSONField):
                        row[field.attname] = json.dumps(row[field.attname], sort_keys=True)
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))

