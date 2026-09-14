"""Долгоживущий scheduler с корректной обработкой остановки контейнера."""

import logging
import signal
import threading

from django.core.management import BaseCommand, CommandError, call_command

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Запускает run_tasks с заданным интервалом до SIGTERM/SIGINT"

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=60)
        parser.add_argument(
            "--once",
            action="store_true",
            help="Выполнить один цикл (для диагностики и тестирования)",
        )

    def _request_stop(self, signum, _frame):
        self.stdout.write(f"Получен сигнал {signum}; scheduler завершится после текущего цикла.")
        self._stop_event.set()

    def handle(self, *args, **options):
        interval = options["interval"]
        if interval < 1:
            raise CommandError("Интервал scheduler должен быть не меньше 1 секунды.")

        self._stop_event = threading.Event()
        previous_handlers = {
            signum: signal.getsignal(signum)
            for signum in (signal.SIGTERM, signal.SIGINT)
        }
        for signum in previous_handlers:
            signal.signal(signum, self._request_stop)

        try:
            while not self._stop_event.is_set():
                try:
                    call_command("run_tasks", stdout=self.stdout, stderr=self.stderr)
                except Exception:  # noqa: BLE001 -- daemon logs and retries transient failures
                    logger.exception("Цикл scheduler завершился с ошибкой")
                    if options["once"]:
                        raise
                if options["once"] or self._stop_event.wait(interval):
                    break
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
