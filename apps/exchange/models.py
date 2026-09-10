"""Модели модуля «exchange»: журнал загрузок и протоколы обработки (Этап 3).

ImportLog хранит результат обработки каждого файла обмена и содержимое
протокола FLCP — протокол доступен участнику информационного обмена (ТЗ).
"""

from django.db import models

from apps.employee.models import ORGS


class ImportLog(models.Model):
    """Запись об обработке одного файла обмена (протокол FLCP)."""

    class Kind(models.TextChoices):
        IRP = "irp", "Обращения (G1*)"
        USERS = "users", "Сотрудники (users*)"
        EXCEL = "excel", "Excel"

    class Status(models.TextChoices):
        OK = "ok", "Обработан без ошибок"
        ERROR = "error", "Обработан с ошибками"

    org = models.IntegerField(choices=ORGS, verbose_name="Организация")
    kind = models.CharField(max_length=10, choices=Kind.choices, verbose_name="Тип")
    filename = models.CharField(max_length=200, verbose_name="Имя файла")
    status = models.CharField(
        max_length=6, choices=Status.choices, verbose_name="Статус"
    )
    rows = models.PositiveIntegerField(default=0, verbose_name="Записей обработано")
    flcp = models.TextField(blank=True, verbose_name="Протокол FLCP")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда")

    class Meta:
        verbose_name = "Загрузка файла"
        verbose_name_plural = "Обмен данными (загрузки)"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "-created_at"], name="exchange_org_created_idx")
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.get_status_display()})"
