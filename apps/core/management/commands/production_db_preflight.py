"""Fail closed before applying migrations to an unknown production database."""

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections

EXPECTED_TABLES = {"employee_employee", "journal_irp", "journal_irptheme"}


def _columns(cursor, table_name: str) -> dict[str, str]:
    cursor.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        """,
        [table_name],
    )
    return dict(cursor.fetchall())


def classify_schema(tables: set[str], theme_columns: dict[str, str]) -> str:
    """Return empty/current/legacy/unknown without mutating the database."""
    application_tables = {
        table for table in tables if table.startswith(("employee_", "journal_"))
    }
    if not application_tables:
        return "empty"
    if not EXPECTED_TABLES.issubset(tables):
        return "unknown"

    # v1 хранит ключ темы в code а v2 использует id и естественный составной ключ
    if theme_columns.get("code") in {"character varying", "text"}:
        return "legacy"
    if (
        theme_columns.get("id") == "bigint"
        and "code_name" in theme_columns
        and "version" in theme_columns
    ):
        return "current"
    return "unknown"


class Command(BaseCommand):
    help = "Check that the target PostgreSQL database is safe for v2 migrations."

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options):
        connection = connections[options["database"]]
        try:
            connection.ensure_connection()
            if connection.vendor != "postgresql":
                raise CommandError("Production database must be PostgreSQL.")
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version_num")
                server_version = int(cursor.fetchone()[0])
                if server_version < 140000:
                    raise CommandError("PostgreSQL 14 or newer is required.")

                cursor.execute("SHOW transaction_read_only")
                if cursor.fetchone()[0] == "on":
                    raise CommandError("Database is read-only; migrations cannot run.")

                tables = set(connection.introspection.table_names(cursor))
                theme_columns = (
                    _columns(cursor, "journal_irptheme")
                    if "journal_irptheme" in tables
                    else {}
                )
                schema_kind = classify_schema(tables, theme_columns)
        except CommandError:
            raise
        except Exception as error:
            raise CommandError(f"Database preflight failed: {error}") from error

        if schema_kind == "legacy":
            raise CommandError(
                "Legacy journal.portal.tfoms schema detected. Refusing in-place migrations: "
                "migrate v1 data into a separate v2 database using GUID, n_irp and "
                "(code_name, version) mappings."
            )
        if schema_kind == "unknown":
            raise CommandError(
                "Unknown or partially initialized journal schema detected. Refusing migrations."
            )
        if schema_kind == "current" and "django_migrations" not in tables:
            raise CommandError(
                "v2-like tables exist without Django migration history. Refusing migrations."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Production database preflight passed: schema={schema_kind}, "
                f"PostgreSQL={server_version}."
            )
        )
