"""Create only the configured missing PostgreSQL database; never drop existing data."""
import psycopg
from psycopg import sql
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create the configured PostgreSQL database if missing, through maintenance database postgres"

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("bootstrap_database requires PostgreSQL; disable MARKETDATA_SQLITE_TEST")
        params = connection.get_connection_params()
        target = params.pop("dbname")
        params["dbname"] = "postgres"
        try:
            with psycopg.connect(**params, autocommit=True) as maintenance:
                with maintenance.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [target])
                    if cursor.fetchone():
                        self.stdout.write("Configured database already exists; no changes made")
                        return
                    cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        except psycopg.errors.DuplicateDatabase:
            self.stdout.write("Configured database was created concurrently; no data changed")
            return
        except psycopg.Error as exc:
            raise CommandError(f"Database initialization failed ({type(exc).__name__}, SQLSTATE={exc.sqlstate or 'unavailable'}); details suppressed") from None
        self.stdout.write("Created configured PostgreSQL database; run migrate next")
