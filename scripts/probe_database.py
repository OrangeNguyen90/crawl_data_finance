"""Read-only probe. Never print connection details or exception text."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.db import connection

try:
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
    print(f"Database probe: OK ({connection.vendor})")
except Exception as exc:
    print(f"Database probe: FAILED ({type(exc).__name__}); connection details suppressed")
    sys.exit(1)
