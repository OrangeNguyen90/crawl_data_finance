"""Download the public FirstRate ES sample linked by its official product page."""
import sys
from pathlib import Path
import requests
import zipfile
url = "https://frd001.s3.us-east-2.amazonaws.com/frd_sample_futures_ES.zip"
path = Path(__file__).resolve().parents[1] / "live_evidence/firstrate_ES_sample.zip"
try:
    with requests.get(url, stream=True, timeout=(10, 60), allow_redirects=False) as response:
        print("FirstRate public sample HTTP", response.status_code)
        response.raise_for_status()
        size = 0
        with path.open("wb") as handle:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise ValueError("Sample size exceeds limit")
                handle.write(chunk)
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist()[:20]:
            print(item.filename, item.file_size)
except requests.RequestException as exc:
    print("Sample network failed:", type(exc).__name__)
    sys.exit(1)

