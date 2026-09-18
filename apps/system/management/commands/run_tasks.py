"""Планировщик и worker очереди автоматизированных заданий."""

from apps.system.models import (
    TaskAlreadyRunning,
    TaskDisabled,
    TaskJob,
    TaskRun,
    TaskRunSuperseded,
)
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Ставит плановые задания в очередь и обрабатывает готовые попытки"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true", dest="all_tasks",
            help="Поставить в очередь все активные задания независимо от расписания",
        )
        parser.add_argument(
            "--recover-only", action="store_true",
            help="Только закрыть зависшие запуски, не обрабатывать очередь",
        )
        parser.add_argument(
            "--stale-after", type=int,
            help="Считать запуск зависшим после указанного числа секунд",
        )
        parser.add_argument(
            "--limit", type=int, default=100,
            help="Максимум попыток из очереди за один проход (по умолчанию 100)",
        )

    def handle(self, *args, **opts):
        recovered = TaskJob.recover_stale(stale_after_seconds=opts.get("stale_after"))
        if recovered:
            self.stdout.write(self.style.WARNING(f"Зависших запусков закрыто: {recovered}"))
        if opts.get("recover_only"):
            return

        tasks = TaskJob.objects.filter(enabled=True)
        tasks = tasks if opts.get("all_tasks") else [task for task in tasks if task.due]
        queued = 0
        for task in tasks:
            try:
                task.enqueue()
                queued += 1
            except (TaskAlreadyRunning, TaskDisabled):
                continue
        if queued:
            self.stdout.write(f"Поставлено в очередь: {queued}")

        limit = max(1, opts["limit"])
        run_ids = list(
            TaskRun.objects.filter(
                finished_at__isnull=True,
                started_at__isnull=True,
                available_at__lte=timezone.now(),
                task__enabled=True,
            ).order_by("available_at", "pk").values_list("pk", flat=True)[:limit]
        )
        if not run_ids:
            self.stdout.write("Нет заданий для запуска: очередь пуста.")
            return
        for run_id in run_ids:
            try:
                run = TaskJob.execute_run(run_id)
            except TaskDisabled:
                continue
            except TaskRunSuperseded:
                self.stdout.write(self.style.WARNING(f"run {run_id}: уже завершён recovery"))
                continue
            if run is None:
                continue
            self.stdout.write(
                f"task {run.task_id}, попытка {run.attempt}/{run.max_attempts}: {run.result}"
            )
            if run.log:
                self.stdout.write(f"  {run.log[:2000]}")
