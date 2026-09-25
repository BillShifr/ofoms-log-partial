"""Модуль «employee»: пользователи (сотрудники) Системы.

Перенос из v1 (journal.portal.tfoms) + расширения Этапа 1:
- блокировка учётной записи при многократных неудачных попытках входа
  (ТЗ разд. 3.1: не более 10 попыток без разблокировки администратором);
- расширена длина должности, добавлен поиск ФИО.
"""

import uuid

from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.db.models import Case, ExpressionWrapper, F, Value, When
from django.utils import timezone

# коды организаций сохраняют совместимость с v1
ORGS = (
    (81000, "ТФОМС"),
    (81001, "СОГАЗ - МЕД"),
    (81007, "Капитал МС"),
    (81008, "АльфаСтрахование - ОМС"),
)

TFOMS = 81000


class Employee(AbstractUser):
    """Пользователь Системы (сотрудник фонда или СМО)."""

    job_title = models.CharField(
        max_length=120, blank=True, null=True, verbose_name="Должность"
    )
    org = models.IntegerField(
        choices=ORGS, db_index=True, verbose_name="Организация",
    )
    guid = models.UUIDField(
        unique=True, editable=False, verbose_name="Идентификатор (GUID)",
        default=uuid.uuid4,
    )
    failed_attempts = models.PositiveSmallIntegerField(
        default=0, verbose_name="Неудачные попытки входа (счётчик)"
    )
    lock_until = models.DateTimeField(
        null=True, blank=True, verbose_name="Заблокирован до"
    )

    class Meta:
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"
        ordering = ["last_name", "first_name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(org__in=tuple(code for code, _ in ORGS)),
                name="employee_org_valid",
            )
        ]

    def full_name(self) -> str:
        return " ".join(part for part in (self.last_name, self.first_name) if part).strip()

    full_name.short_description = "ФИО"

    def __str__(self) -> str:
        return self.full_name() or self.username

    def record_failed_login(self) -> None:
        """Увеличивает счётчик неудачных попыток; блокирует при превышении лимита."""
        from django.conf import settings

        limit = settings.SECURITY_MAX_FAILED_LOGIN_ATTEMPTS
        permanent_lock = timezone.now().replace(year=9999)
        type(self).objects.filter(pk=self.pk).update(
            failed_attempts=Case(
                When(
                    failed_attempts__lt=limit,
                    then=ExpressionWrapper(
                        F("failed_attempts") + 1,
                        output_field=models.PositiveSmallIntegerField(),
                    ),
                ),
                default=F("failed_attempts"),
                output_field=models.PositiveSmallIntegerField(),
            ),
            lock_until=Case(
                When(failed_attempts__gte=limit - 1, then=Value(permanent_lock)),
                default=F("lock_until"),
            ),
        )
        self.refresh_from_db(fields=["failed_attempts", "lock_until"])

    def reset_failed_logins(self) -> None:
        self.failed_attempts = 0
        self.lock_until = None
        self.save(update_fields=["failed_attempts", "lock_until"])

    @property
    def is_locked(self) -> bool:
        return bool(self.lock_until) and self.lock_until > timezone.now()


class GroupProxy(Group):
    """Прокси-модель групп пользователей (роли)."""

    class Meta:
        proxy = True
        verbose_name = "Группа (роль)"
        verbose_name_plural = "Группы (роли)"
