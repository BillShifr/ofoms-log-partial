from django.test import SimpleTestCase

from apps.core.management.commands.production_db_preflight import classify_schema


class ProductionDatabasePreflightTests(SimpleTestCase):
    def test_empty_database_is_allowed(self):
        self.assertEqual(classify_schema(set(), {}), "empty")

    def test_v2_schema_is_allowed(self):
        self.assertEqual(
            classify_schema(
                {"employee_employee", "journal_irp", "journal_irptheme"},
                {"id": "bigint", "code_name": "character varying", "version": "integer"},
            ),
            "current",
        )

    def test_legacy_theme_primary_key_is_rejected(self):
        self.assertEqual(
            classify_schema(
                {"employee_employee", "journal_irp", "journal_irptheme"},
                {
                    "code": "character varying",
                    "code_name": "character varying",
                    "version": "integer",
                },
            ),
            "legacy",
        )

    def test_partial_schema_is_unknown(self):
        self.assertEqual(classify_schema({"journal_irp"}, {}), "unknown")
