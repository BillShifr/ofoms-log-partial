"""Модель «Журнал событий» (ТЗ разд. 3.4).

События: тип, модуль, инициатор, атрибуты, IP-адрес, результат,
время начала и завершения. Поддерживает фильтрацию по реквизитам.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger("apps.core")


class ConsumedToken(models.Model):
    """Одноразовый идентификатор уже обмененного временного JWT."""

    jti = models.UUIDField(primary_key=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Использованный временный токен"
        verbose_name_plural = "Использованные временные токены"


class EventLog(models.Model):
    """Запись журнала событий функционирования Системы."""

    class EventType(models.TextChoices):
        LOGIN = "login", "Вход в систему"
        LOGIN_FAILED = "login_failed", "Неудачная аутентификация"
        LOGOUT = "logout", "Выход из системы"
        CREATE = "create", "Создание записи"
        UPDATE = "update", "Изменение записи"
        DELETE = "delete", "Удаление записи"
        IMPORT = "import", "Импорт данных"
        EXPORT = "export", "Экспорт данных"
        PRINT = "print", "Печать"
        SEND = "send", "Отправка/переадресация"
        BLOCK = "block", "Блокировка учётной записи"
        UNBLOCK = "unblock", "Разблокировка учётной записи"
        TASK = "task", "Выполнение автоматизированного задания"
        OTHER = "other", "Прочее"

    class Result(models.TextChoices):
        OK = "ok", "Успешно"
        FAILED = "failed", "Ошибка"
        DENIED = "denied", "Доступ запрещён"

    module = models.CharField(max_length=64, verbose_name="Модуль", db_index=True)
    event_type = models.CharField(
        max_length=24, choices=EventType.choices, verbose_name="Тип события", db_index=True
    )
    result = models.CharField(
        max_length=8, choices=Result.choices, default=Result.OK, verbose_name="Результат"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        verbose_name="Инициатор",
    )
    target = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Объект (атрибуты события)"
    )
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="Начало события")
    finished_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Завершение события"
    )
    duration_ms = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Длительность (мс)"
    )
    detail = models.TextField(blank=True, default="", verbose_name="Детали")

    class Meta:
        verbose_name = "Событие"
        verbose_name_plural = "Журнал событий"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["module", "event_type"]),
            models.Index(fields=["user", "-id"]),
            models.Index(fields=["started_at"], name="core_event_started_idx"),
            models.Index(fields=["result", "-id"], name="core_event_result_id_idx"),
        ]

    def __str__(self):
        return f"{self.id}: {self.get_event_type_display()} / {self.module} / {self.user_id}"


def log_event(
    *,
    module: str,
    event_type: "str | EventLog.EventType",
    user=None,
    result: "str | EventLog.Result" = EventLog.Result.OK,
    target: str = "",
    ip: str | None = None,
    detail: str = "",
    obj: "EventLog | None" = None,
    duration_ms: int | None = None,
    pending: bool = False,
) -> "EventLog":
    """Утилита записи события в журнал. Если передан obj — завершает запись."""
    if obj is None:
        entry = EventLog.objects.create(
            module=module,
            event_type=event_type,
            result=result,
            user=user,
            target=target,
            ip=ip,
            detail=detail,
        )
        if not pending:
            entry.duration_ms = duration_ms if duration_ms is not None else 0
            entry.finished_at = entry.started_at + timedelta(milliseconds=entry.duration_ms)
            entry.save(update_fields=["duration_ms", "finished_at"])
        return entry
    obj.finished_at = timezone.now()
    obj.duration_ms = (
        duration_ms
        if duration_ms is not None
        else max(0, int((obj.finished_at - obj.started_at).total_seconds() * 1000))
    )
    obj.result = result
    obj.detail = detail or obj.detail
    obj.save(update_fields=["result", "detail", "duration_ms", "finished_at"])
    return obj
