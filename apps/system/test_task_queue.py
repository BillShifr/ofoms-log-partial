import uuid
import datetime
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.core.models import ConsumedToken, EventLog
from apps.employee.models import Employee
from apps.system.forms import TaskForm
from apps.system.models import TaskAlreadyRunning, TaskJob, TaskRun
from apps.system.tasks import TASK_COMMAND_LABELS, run_command, validate_command_params


class TaskCommandRegistryTests(TestCase):
    def test_registry_contains_only_real_builtin_actions(self):
        self.assertNotIn("noop", TASK_COMMAND_LABELS)
        self.assertIn("database_health", TASK_COMMAND_LABELS)
        self.assertIn("expired_token_cleanup", TASK_COMMAND_LABELS)
        self.assertIn("exchange_import", TASK_COMMAND_LABELS)

    def test_parameters_are_typed_and_reject_unknown_keys(self):
        self.assertEqual(
            validate_command_params("expired_token_cleanup", {"batch_size": "25"}),
            {"batch_size": 25},
        )
        with self.assertRaisesMessage(Exception, "Неизвестные параметры"):
            validate_command_params("expired_token_cleanup", {"unexpected": True})

    def test_expired_token_cleanup_is_bounded_and_real(self):
        expired = [
            ConsumedToken.objects.create(
                jti=uuid.uuid4(),
                expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
                - timedelta(minutes=index + 1),
            )
            for index in range(3)
        ]
        ConsumedToken.objects.create(
            jti=uuid.uuid4(),
            expires_at=datetime.datetime.now(tz=datetime.timezone.utc)
            + timedelta(hours=1),
        )

        result = run_command("expired_token_cleanup", {"batch_size": 2})

        self.assertIn("2", result)
        self.assertEqual(
            ConsumedToken.objects.filter(pk__in=[token.pk for token in expired]).count(), 1
        )


class TaskQueueTests(TestCase):
    def setUp(self):
        self.user = Employee.objects.create_user(
            username="task_queue_admin", password="test", org=81000
        )

    def make_task(self, **overrides):
        values = {
            "name": "Проверка очереди",
            "command": "database_health",
            "run_mode": TaskJob.RunMode.MANUAL,
            "enabled": True,
            "max_retries": 1,
            "retry_delay_seconds": 0,
        }
        values.update(overrides)
        return TaskJob.objects.create(**values)

    def test_form_persists_typed_action_parameters(self):
        form = TaskForm(data={
            "name": "Очистка",
            "command": "expired_token_cleanup",
            "run_mode": TaskJob.RunMode.MANUAL,
            "enabled": "on",
            "param__expired_token_cleanup__batch_size": "250",
            "max_retries": "3",
            "retry_delay_seconds": "15",
        })

        self.assertTrue(form.is_valid(), form.errors)
        task = form.save()
        self.assertEqual(task.params, {"batch_size": 250})
        self.assertEqual(task.max_retries, 3)
        self.assertEqual(task.retry_delay_seconds, 15)

    def test_enqueue_is_non_blocking_and_prevents_duplicate_active_run(self):
        task = self.make_task()

        run = task.enqueue(user=self.user)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.QUEUED)
        self.assertIsNone(run.started_at)
        self.assertEqual(run.requested_by, self.user)
        self.assertIsNone(run.audit_event.finished_at)
        with self.assertRaises(TaskAlreadyRunning):
            task.enqueue(user=self.user)

    def test_failure_creates_distinct_retry_then_success(self):
        task = self.make_task()
        first = task.enqueue(user=self.user)

        with patch(
            "apps.system.tasks.run_command",
            side_effect=[RuntimeError("private detail"), "Готово"],
        ):
            TaskJob.execute_run(first.pk)
            retry = TaskRun.objects.get(task=task, attempt=2)
            TaskJob.execute_run(retry.pk)

        task.refresh_from_db()
        first.refresh_from_db()
        retry.refresh_from_db()
        self.assertEqual(first.result, TaskRun.Result.FAILED)
        self.assertNotIn("private detail", first.log)
        self.assertEqual(retry.result, TaskRun.Result.OK)
        self.assertEqual(task.status, TaskJob.Status.COMPLETED)
        self.assertEqual(task.last_result, TaskJob.Result.OK)
        self.assertEqual(
            EventLog.objects.filter(event_type=EventLog.EventType.TASK).count(), 2
        )

    def test_worker_command_processes_manual_queue(self):
        task = self.make_task(max_retries=0, params={"check_migrations": False})
        run = task.enqueue(user=self.user)

        call_command("run_tasks")

        run.refresh_from_db()
        task.refresh_from_db()
        self.assertEqual(run.result, TaskRun.Result.OK)
        self.assertEqual(task.status, TaskJob.Status.COMPLETED)
