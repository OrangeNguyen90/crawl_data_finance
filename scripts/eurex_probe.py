"""Read-only GraphQL introspection. Credentials only from the environment."""
import json
import os
from pathlib import Path
import requests

root = Path(__file__).resolve().parents[1]
key = os.getenv("EUREX_API_KEY")
if not key:
    print("Eurex GraphQL: SKIP (configure EUREX_API_KEY; no key is printed)")
    raise SystemExit(2)
query = "{ __schema { queryType { name fields { name args { name type { kind name ofType { kind name } } } type { kind name ofType { kind name ofType { kind name } } } } } types { name kind fields { name type { kind name ofType { kind name ofType { kind name } } } } } } }"
try:
    with requests.post("https://api.developer.deutsche-boerse.com/eurex-prod-graphql",
        headers={"X-DBP-APIKEY": key}, json={"query": query}, timeout=(10, 40), allow_redirects=False) as response:
        print("Eurex GraphQL HTTP", response.status_code)
        if response.status_code == 200:
            data = response.json()
            (root / "live_evidence/eurex_schema.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
            print("Schema saved:", "data" in data, "errors:", bool(data.get("errors")))
except requests.RequestException as exc:
    print("Eurex GraphQL:", type(exc).__name__)

