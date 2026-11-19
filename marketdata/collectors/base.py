import tempfile
import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import requests


class CollectorError(Exception):
    """Safe operational message without credentials or response bodies."""


class CollectorCancelled(CollectorError):
    pass


class BaseCollector(ABC):
    allowed_host = ""
    max_bytes = 100 * 1024 * 1024

    def __init__(self, session=None):
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({"User-Agent": "GlobalFuturesCollector/2.0 (public market data research)"})
        self.retry_count = 0

    def close(self):
        self.session.close()

    def _check_url(self, url):
        try:
            parsed = urlparse(url)
            valid = (parsed.scheme == "https" and parsed.hostname == self.allowed_host
                     and parsed.port in (None, 443) and not parsed.username and not parsed.password)
        except ValueError:
            valid = False
        if not valid:
            raise CollectorError("Source URL is outside the approved HTTPS host")

    def fetch_file(self, url):
        """Bounded download; disk spill above 4 MiB. Caller closes returned handle."""
        self._check_url(url)
        for attempt in range(3):
            response = None
            target = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
            success = False
            try:
                response = self.session.get(url, timeout=(10, 60), stream=True, allow_redirects=False)
                status = response.status_code
                if status in (429, 500, 502, 503, 504) and attempt < 2:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = min(int(retry_after), 30) if retry_after.isdigit() else 2 ** attempt
                    self.retry_count += 1
                    response.close()
                    time.sleep(delay)
                    continue
                if status != 200:
                    raise CollectorError(f"Source returned HTTP {status}; redirects are not followed")
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise CollectorError("Download exceeds size limit")
                    target.write(chunk)
                target.seek(0)
                success = True
                return target
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
                if attempt == 2:
                    raise CollectorError("Source transport failed after three attempts") from None
                self.retry_count += 1
                time.sleep(2 ** attempt)
            except requests.RequestException:
                raise CollectorError("Source request failed") from None
            finally:
                if response is not None:
                    response.close()
                if not success:
                    target.close()
        raise CollectorError("Source request failed")

    def fetch(self, url):
        with self.fetch_file(url) as handle:
            return handle.read()

    def download(self, url):
        return self.fetch(url)

    @abstractmethod
    def discover(self):
        raise NotImplementedError

    @abstractmethod
    def parse(self, content):
        raise NotImplementedError

    @abstractmethod
    def validate(self, row):
        raise NotImplementedError

    @abstractmethod
    def normalize(self, row, report_type, scope):
        raise NotImplementedError

    @abstractmethod
    def persist(self, rows, source_file):
        raise NotImplementedError

    @abstractmethod
    def sync(self):
        raise NotImplementedError

    @abstractmethod
    def backfill(self, start, end):
        raise NotImplementedError

