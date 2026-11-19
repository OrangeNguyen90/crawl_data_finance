"""Configured, schema-verified Eurex reference queries; no price data is generated."""
import json
import time
from pathlib import Path

import requests
from django.conf import settings
from django.db import transaction

from marketdata.collectors.base import BaseCollector, CollectorError
from marketdata.collectors.statistics import instrument_for
from marketdata.models import CollectorCheckpoint, DataSource
from marketdata.runtime import fingerprint, issue, job_run, store_raw

URL = "https://api.developer.deutsche-boerse.com/eurex-prod-graphql"


class EurexCollector(BaseCollector):
    allowed_host = "api.developer.deutsche-boerse.com"

    def discover(self):
        return [URL]

    def graphql(self, query, variables=None):
        self._check_url(URL)
        if not settings.EUREX_API_KEY:
            raise CollectorError("EUREX_API_KEY is required; use the public documentation or a dedicated free key")
        for attempt in range(3):
            response = None
            try:
                response = self.session.post(URL, headers={"X-DBP-APIKEY": settings.EUREX_API_KEY},
                    json={"query": query, "variables": variables or {}}, timeout=(10, 60), allow_redirects=False, stream=True)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    self.retry_count += 1
                    response.close()
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code != 200:
                    raise CollectorError(f"Eurex GraphQL HTTP {response.status_code}; verify endpoint availability")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > self.max_bytes:
                        raise CollectorError("Eurex response exceeds size limit")
                payload = json.loads(content)
                if payload.get("errors") or not isinstance(payload.get("data"), dict):
                    raise CollectorError("Eurex GraphQL errors or missing data; response details suppressed")
                return payload
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise CollectorError("Eurex transport or JSON failed") from None
                self.retry_count += 1
                time.sleep(2 ** attempt)
            finally:
                if response is not None:
                    response.close()
        raise CollectorError("Eurex request failed")

    def introspect(self):
        return self.graphql("{ __schema { queryType { name fields { name } } } }")

    def parse(self, content):
        data = json.loads(content)
        if not isinstance(data, list):
            raise CollectorError("Eurex normalized reference result must be a list")
        yield from data

    def validate(self, row):
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str) or not row["symbol"].strip():
            raise CollectorError("Missing exact Eurex identifier")
        if not isinstance(row.get("name"), str) or not row["name"]:
            raise CollectorError("Missing Eurex instrument name")

    def normalize(self, row, report_type=None, scope=None):
        self.validate(row)
        return row

    def persist(self, rows, source_file):
        inserted = updated = 0
        from marketdata.models import Instrument
        for row in rows:
            self.validate(row)
            exists = Instrument.objects.filter(exchange="EUREX", symbol=row["symbol"], expiration_date=row.get("expiration")).exists()
            obj = instrument_for(source_file.source, "EUREX", row["symbol"], row["name"],
                row.get("contract_type", "reference_product"), expiration=row.get("expiration"))
            obj.metadata = {**obj.metadata, "reference": row["raw_fields"], "source_file_id": source_file.pk}
            obj.currency = row.get("currency") or obj.currency
            if row.get("tick_size") is not None:
                from decimal import Decimal, InvalidOperation
                try:
                    tick = Decimal(str(row["tick_size"]))
                    if not tick.is_finite() or tick <= 0 or tick >= Decimal("1e16") or tick.as_tuple().exponent < -8:
                        raise ValueError
                except (ValueError, InvalidOperation):
                    raise CollectorError("Invalid Eurex tick size") from None
                obj.tick_size = tick
            obj.save()
            inserted += int(not exists)
            updated += int(exists)
        return inserted, updated, 0

    def sync(self, job=None):
        # Deployment-specific field names must be verified by introspection, never guessed.
        source = DataSource.objects.get(name="eurex")
        with job_run(source, "sync", {}, job, transport=self) as running:
            config_path = getattr(settings, "EUREX_QUERY_FILE", "")
            if not config_path:
                raise CollectorError("Eurex endpoint currently unverified (live HTTP 404); configure EUREX_QUERY_FILE after schema verification")
            config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
            for key in ("query", "root", "fields"):
                if key not in config:
                    raise CollectorError("Eurex query config requires query, root and fields")
            variables = dict(config.get("variables", {}))
            seen = set()
            for page in range(1000):
                payload = self.graphql(config["query"], variables)
                raw = store_raw(source, json.dumps(payload).encode(), URL, "reference.json", "json")
                key = fingerprint({"query": config["query"], "variables": variables})
                previous = CollectorCheckpoint.objects.filter(source=source, key=key).first()
                result = payload["data"]
                for component in config["root"].split("."):
                    result = result[component]
                if not isinstance(result, list):
                    raise CollectorError("Eurex configured root is not a list")
                if not previous or previous.raw_file_id != raw.pk:
                    with transaction.atomic():
                        rows = []
                        for original in result:
                            row = {dest: original.get(field) for dest, field in config["fields"].items()}
                            row["raw_fields"] = original
                            rows.append(row)
                        counts = self.persist(rows, raw)
                        raw.processing_status = "complete"
                        raw.save(update_fields=["processing_status"])
                        CollectorCheckpoint.objects.update_or_create(source=source, key=key, defaults={"raw_file": raw})
                    running.records_inserted += counts[0]
                    running.records_updated += counts[1]
                running.records_downloaded += 1
                running.save(update_fields=["records_downloaded", "records_inserted", "records_updated"])
                pagination = config.get("pagination")
                if not pagination:
                    break
                cursor = payload["data"]
                for component in pagination["next_path"].split("."):
                    cursor = cursor[component]
                if cursor is None:
                    break
                if str(cursor) in seen:
                    raise CollectorError("Eurex pagination cursor repeated")
                seen.add(str(cursor))
                variables[pagination["variable"]] = cursor
                time.sleep(1)
            else:
                raise CollectorError("Eurex pagination limit exceeded")
        return running

    def backfill(self, start, end, **kwargs):
        raise CollectorError("Reference API historical snapshots are not verified")

