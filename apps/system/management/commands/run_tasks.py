"""Запуск автоматизированных заданий по расписанию (ТЗ разд. 3.6).

Выполняет все активные задания с режимом «По расписанию», у которых наступил
интервал (due). Запуск по требованию: управляющий планировщик (systemd
timer / Cron) вызывает: python manage.py run_tasks
"""
from apps.system.models import TaskAlreadyRunning, TaskJob, TaskRunSuperseded
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Выполняет активные задания с режимом «По расписанию»"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_tasks",
            help="Запустить все активные задания независимо от расписания",
        )
        parser.add_argument(
            "--recover-only",
            action="store_true",
            help="Только закрыть зависшие запуски, не запускать задания",
        )
        parser.add_argument(
            "--stale-after",
            type=int,
            help="Считать запуск зависшим после указанного числа секунд",
        )

    def handle(self, *args, **opts):
        recovered = TaskJob.recover_stale(
            stale_after_seconds=opts.get("stale_after")
        )
        if recovered:
            self.stdout.write(self.style.WARNING(f"Зависших запусков закрыто: {recovered}"))
        if opts.get("recover_only"):
            return
        qs = TaskJob.objects.filter(enabled=True)
        if opts.get("all_tasks"):
            qs = qs.all()
        else:
            qs = [t for t in qs if t.due]
        if not qs:
            self.stdout.write("Нет заданий для запуска.")
            return
        for task in qs:
            try:
                run = task.run(user=None)
            except TaskAlreadyRunning:
                self.stdout.write(
                    self.style.WARNING(f"task {task.pk}: уже выполняется, пропущено")
                )
                continue
            except TaskRunSuperseded:
                self.stdout.write(
                    self.style.WARNING(
                        f"task {task.pk}: запуск уже закрыт recovery, пропущено"
                    )
                )
                continue
            label = run.result if run.result else "?"
            self.stdout.write(
                self.style.WARNING(f"task {task.pk} [{task.command}]: {label}")
            )
            if run.log:
                self.stdout.write(f"  {run.log[:2000]}")
