from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.core.management.commands.upgrade_legacy_database import (
    audit_legacy_data,
    upgrade_legacy_schema,
)


class LegacyDatabaseUpgradeTests(TransactionTestCase):
    schema = "legacy_upgrade_test"

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            cursor.execute(f'CREATE SCHEMA "{self.schema}"')
            cursor.execute(f'SET search_path TO "{self.schema}"')
            cursor.execute(
                """
                CREATE TABLE employee_employee (
                    id serial PRIMARY KEY,
                    job_title varchar(30),
                    org integer NOT NULL
                );
                CREATE TABLE journal_irptheme (
                    code varchar(14) PRIMARY KEY,
                    title varchar(2000) NOT NULL,
                    version integer NOT NULL,
                    code_name varchar(14) NOT NULL,
                    UNIQUE (code_name, version)
                );
                CREATE TABLE journal_irp (
                    id serial PRIMARY KEY,
                    n_irp varchar(36) NOT NULL,
                    theme_id varchar(14) NOT NULL REFERENCES journal_irptheme(code),
                    date_close date,
                    result smallint,
                    zh_d varchar(10),
                    irp_type smallint NOT NULL,
                    pr_out smallint,
                    date_cross date,
                    time_cross time
                );
                CREATE TABLE journal_xmlfiles (
                    id serial PRIMARY KEY,
                    smo integer NOT NULL,
                    year varchar(4) NOT NULL,
                    month varchar(2) NOT NULL,
                    day varchar(2) NOT NULL,
                    filename varchar(200) NOT NULL,
                    real_filename varchar(200) NOT NULL
                );
                INSERT INTO employee_employee (job_title, org)
                    VALUES ('operator', 81000);
                INSERT INTO journal_irptheme (code, title, version, code_name)
                    VALUES ('01', 'Theme', 3, 'THEME.01');
                INSERT INTO journal_irp (n_irp, theme_id, irp_type)
                    VALUES ('IRP-1', '01', 1);
                INSERT INTO journal_xmlfiles
                    (smo, year, month, day, filename, real_filename)
                    VALUES (81000, '2026', '09', '25', 'a.xml', 'a.xml');
                """
            )

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute("SET search_path TO public")
            cursor.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')

    def test_upgrade_preserves_theme_mapping_and_adds_security_fields(self):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f'SET LOCAL search_path TO "{self.schema}"')
            self.assertEqual(audit_legacy_data(cursor), {})
            upgrade_legacy_schema(cursor)
            cursor.execute(
                """
                    SELECT theme.legacy_code, theme.code_name, irp.theme_id = theme.id
                    FROM journal_irp AS irp
                    JOIN journal_irptheme AS theme ON theme.id = irp.theme_id
                    """
            )
            self.assertEqual(cursor.fetchone(), ("01", "THEME.01", True))
            cursor.execute(
                """
                    SELECT failed_attempts, lock_until
                    FROM employee_employee WHERE id = 1
                    """
            )
            self.assertEqual(cursor.fetchone(), (0, None))
            cursor.execute("SELECT to_regclass('journal_irphistory')")
            self.assertEqual(cursor.fetchone()[0], "journal_irphistory")

    def test_audit_rejects_inconsistent_rows_before_ddl(self):
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{self.schema}"')
            cursor.execute("UPDATE journal_irp SET date_close = DATE '2026-01-01' WHERE id = 1")
            self.assertEqual(
                audit_legacy_data(cursor),
                {"appeals with close date but no result": 1},
            )
