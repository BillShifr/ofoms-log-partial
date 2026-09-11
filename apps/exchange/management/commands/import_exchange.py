"""Автоматическая загрузка файлов обмена из сканируемого каталога
(exchange/in/<org>) — Способ 4 регистрации (ТЗ «Регистрация обращений»).

Обрабатывает users*.xml, G1*.xml и *.xlsx, пишет протокол FLCP в
exchange/out/<org>, переносит файлы в exchange/archive/<org>.
Запуск по расписанию: systemd timer / Cron (см. Этап 8).
"""

from django.core.management.base import BaseCommand

from apps.exchange.importers import import_all


class Command(BaseCommand):
    help = "Обнаруживает и обрабатывает файлы обмена в exchange/in/<org>"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=int,
            action="append",
            dest="orgs",
            help="Ограничить обработку указанными организациями (можно несколько)",
        )

    def handle(self, *args, **opts):
        results = import_all(orgs=opts.get("orgs"))
        if not results:
            self.stdout.write(self.style.WARNING("Файлов для обработки не найдено."))
            return
        for res in results:
            if res.ok:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{res.filename}: обработано записей {res.rows}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"{res.filename}: ошибок {len(res.errors)}"
                    )
                )
