"""Модели общесистемных модулей (ТЗ разд. 3.2–3.8)."""

import logging
from datetime import timedelta
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify

from apps.core.storage import delete_field_file_after_commit
from apps.system.validators import (
    validate_attachment_file,
    validate_document_file,
    validate_image_file,
)

logger = logging.getLogger("apps.system")


class TaskAlreadyRunning(RuntimeError):
    """Задание уже захвачено другим worker-процессом."""


class NewsCategory(models.Model):
    """Категория/тема новости (PRD v3 §2.7)."""

    name = models.CharField(max_length=100, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Код")
    icon = models.CharField(max_length=32, blank=True, default="", verbose_name="SVG-иконка")

    class Meta:
        verbose_name = "Категория новостей"
        verbose_name_plural = "Категории новостей"
        ordering = ["name"]

    def __str__(self):
        return self.name


class NewsItem(models.Model):
    """Новости/уведомления (ТЗ разд. 3.8, PRD v3 §2.7)."""

    def news_cover_upload_to(self, filename):
        return f"news/{timezone.now():%Y/%m}/{filename}"

    title = models.CharField(max_length=200, verbose_name="Заголовок")
    slug = models.SlugField(unique=True, blank=True, verbose_name="Код (авто)")
    summary = models.TextField(blank=True, default="", verbose_name="Краткое описание")
    text = models.TextField(blank=True, default="", verbose_name="Содержание (HTML)")
    category = models.ForeignKey(
        NewsCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="news",
        verbose_name="Категория",
    )
    cover_image = models.ImageField(
        upload_to=news_cover_upload_to,
        null=True,
        blank=True,
        validators=[validate_image_file],
        verbose_name="Обложка",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="news_items",
        verbose_name="Автор",
    )
    is_active = models.BooleanField(default=True, verbose_name="Опубликовано")
    is_pinned = models.BooleanField(default=False, verbose_name="Закреплено сверху")
    views_count = models.PositiveIntegerField(default=0, verbose_name="Просмотров")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата публикации")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-is_pinned", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "news"
            slug, n = base, 1
            while NewsItem.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        return super().save(*args, **kwargs)


@receiver(pre_save, sender=NewsItem)
def capture_replaced_news_cover(sender, instance, **kwargs):
    """Запоминает прежнюю обложку до обновления строки новости."""
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).only("cover_image").first()
    if previous and previous.cover_image.name != instance.cover_image.name:
        instance._replaced_cover_image = previous.cover_image


@receiver(post_save, sender=NewsItem)
def delete_replaced_news_cover_after_commit(sender, instance, **kwargs):
    """Удаляет заменённую обложку после успешного сохранения новой версии."""
    previous = getattr(instance, "_replaced_cover_image", None)
    if previous is not None:
        delete_field_file_after_commit(previous)
        del instance._replaced_cover_image


@receiver(post_delete, sender=NewsItem)
def delete_news_cover_after_commit(sender, instance, **kwargs):
    """Удаляет обложку только после успешного удаления новости из БД."""
    delete_field_file_after_commit(instance.cover_image)


class DocCategory(models.Model):
    """Категория/раздел документации (PRD v3 §2.8)."""

    name = models.CharField(max_length=200, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Код")
    description = models.TextField(blank=True, default="", verbose_name="Описание")
    icon = models.CharField(max_length=32, blank=True, default="", verbose_name="SVG-иконка")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        verbose_name="Родительская категория",
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Категория документации"
        verbose_name_plural = "Категории документации"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    @property
    def docs_count(self):
        return self.docs.count()


class SystemDocument(models.Model):
    """Эксплуатационная документация (ТЗ разд. 3.7, PRD v3 §2.8)."""

    def doc_upload_to(self, filename):
        return f"docs/{timezone.now():%Y/%m}/{filename}"

    title = models.CharField(max_length=200, verbose_name="Наименование")
    slug = models.SlugField(unique=True, blank=True, verbose_name="Код (авто)")
    description = models.TextField(blank=True, default="", verbose_name="Описание")
    category = models.ForeignKey(
        DocCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="docs",
        verbose_name="Категория",
    )
    file = models.FileField(
        upload_to=doc_upload_to,
        validators=[validate_document_file],
        verbose_name="Файл",
    )
    file_size = models.PositiveIntegerField(default=0, verbose_name="Размер (байт)")
    file_type = models.CharField(max_length=16, blank=True, default="", verbose_name="Тип файла")
    version = models.CharField(max_length=16, default="1.0", verbose_name="Версия")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_docs",
        verbose_name="Загрузил",
    )
    downloads_count = models.PositiveIntegerField(default=0, verbose_name="Скачиваний")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата загрузки")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")

    class Meta:
        verbose_name = "Документ"
        verbose_name_plural = "Документация"
        ordering = ["sort_order", "-id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title.split(".")[0]) or "doc"
            slug, n = base, 1
            while SystemDocument.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        return super().save(*args, **kwargs)

    @property
    def size_display(self) -> str:
        size = self.file_size or (self.file.size if self.file else 0)
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} МБ"
        if size >= 1024:
            return f"{size / 1024:.0f} КБ"
        return f"{size} Б"

    @property
    def is_video(self) -> bool:
        return PurePosixPath(self.file.name).suffix.lower() in {".mp4", ".ogv", ".webm"}


@receiver(post_delete, sender=SystemDocument)
def delete_document_file_after_commit(sender, instance, **kwargs):
    """Удаляет файл только после успешного удаления документа из БД."""
    delete_field_file_after_commit(instance.file)


class Conversation(models.Model):
    """Диалог/групповой чат (PRD v3 §2.6)."""

    title = models.CharField(max_length=200, blank=True, default="", verbose_name="Название")
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="conversations", verbose_name="Участники"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        verbose_name = "Диалог"
        verbose_name_plural = "Диалоги"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or ", ".join(
            p.full_name() for p in self.participants.all()[:3]
        )

    @property
    def display_title(self) -> str:
        """Заголовок диалога без текущего пользователя (для личных чатов)."""
        if self.title:
            return self.title
        others = [
            p.full_name()
            for p in self.participants.all()
        ]
        return ", ".join(others[:3]) or "Диалог"


class MessageThread(models.Model):
    """Тема/ветка внутри диалога (PRD v3 §2.6)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="threads",
        verbose_name="Диалог",
    )
    title = models.CharField(max_length=200, blank=True, default="", verbose_name="Тема")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_threads",
        verbose_name="Создал",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    is_closed = models.BooleanField(default=False, verbose_name="Закрыта")

    class Meta:
        verbose_name = "Тема"
        verbose_name_plural = "Темы"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"Тема #{self.pk}"


class MessageReply(models.Model):
    """Сообщение/ответ в теме диалога (PRD v3 §2.6)."""

    thread = models.ForeignKey(
        MessageThread,
        on_delete=models.CASCADE,
        related_name="replies",
        verbose_name="Тема",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="thread_replies",
        verbose_name="Автор",
    )
    body = models.TextField(verbose_name="Текст")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        verbose_name="Ответ на",
    )
    reactions = models.JSONField(default=dict, blank=True, verbose_name="Реакции")
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="read_replies", blank=True, verbose_name="Прочитано"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Отправлено")
    edited_at = models.DateTimeField(null=True, blank=True, verbose_name="Изменено")

    class Meta:
        verbose_name = "Сообщение диалога"
        verbose_name_plural = "Сообщения диалогов"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "-created_at"], name="system_reply_latest_idx")
        ]

    def __str__(self):
        return f"{self.author_id}: {self.body[:50]}"

    def is_new_for(self, user) -> bool:
        return self.author_id != user.pk and not self.read_by.filter(pk=user.pk).exists()


class MessageAttachment(models.Model):
    """Файл-вложение к сообщению диалога (PRD v3 §2.6)."""

    def attachment_upload_to(self, filename):
        return f"messages/{timezone.now():%Y/%m}/{filename}"

    reply = models.ForeignKey(
        MessageReply,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="Сообщение",
    )
    file = models.FileField(
        upload_to=attachment_upload_to,
        validators=[validate_attachment_file],
        verbose_name="Файл",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_attachments",
        verbose_name="Загрузил",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда")

    class Meta:
        verbose_name = "Вложение диалога"
        verbose_name_plural = "Вложения диалогов"
        ordering = ["created_at"]

    def __str__(self):
        return self.file.name


@receiver(post_delete, sender=MessageAttachment)
def delete_message_attachment_after_commit(sender, instance, **kwargs):
    """Удаляет файл вложения после успешного удаления сообщения или диалога."""
    delete_field_file_after_commit(instance.file)


class TaskJob(models.Model):
    """Автоматизированное задание (ТЗ разд. 3.6, PRD v3 §2.11).

    Задание ссылается на команду из реестра TASK_COMMANDS (apps.system.tasks).
    Запуск: вручную с экрана или автоматически по интервалу (interval_minutes)
    через management-команду run_tasks. Поддерживаются статусы, исполнитель,
    приоритет, заметки, файлы и отчёты.
    """

    class Status(models.TextChoices):
        CREATED = "created", "Создана"
        RUNNING = "running", "В работе"
        COMPLETED = "completed", "Завершена"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменена"

    class Priority(models.IntegerChoices):
        LOW = 0, "Низкий"
        MEDIUM = 1, "Средний"
        HIGH = 2, "Высокий"

    class RunMode(models.TextChoices):
        MANUAL = "manual", "Только вручную"
        SCHEDULED = "scheduled", "По расписанию"

    name = models.CharField(max_length=120, verbose_name="Наименование")
    command = models.CharField(max_length=64, verbose_name="Команда")
    description = models.TextField(blank=True, default="", verbose_name="Описание")
    params = models.JSONField(default=dict, blank=True, verbose_name="Параметры (JSON)")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREATED,
        verbose_name="Статус",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
        verbose_name="Исполнитель",
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices, default=Priority.LOW, verbose_name="Приоритет"
    )
    run_mode = models.CharField(
        max_length=16,
        choices=RunMode.choices,
        default=RunMode.MANUAL,
        verbose_name="Режим запуска",
    )
    interval_minutes = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Интервал (минут)"
    )
    enabled = models.BooleanField(default=True, verbose_name="Активно")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_tasks",
        verbose_name="Создал",
    )
    last_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Последний запуск")
    last_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Последнее завершение")
    last_result = models.CharField(
        max_length=16, blank=True, default="", verbose_name="Результат последнего запуска"
    )
    last_log = models.TextField(blank=True, default="", verbose_name="Лог последнего запуска")

    class Meta:
        verbose_name = "Задание"
        verbose_name_plural = "Задачи"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(command__in=("noop", "exchange_import")),
                name="system_task_command_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("created", "running", "completed", "failed", "cancelled")
                ),
                name="system_task_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__in=(0, 1, 2)),
                name="system_task_priority_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(run_mode="manual", interval_minutes__isnull=True)
                    | models.Q(
                        run_mode="scheduled",
                        interval_minutes__isnull=False,
                        interval_minutes__gte=1,
                    )
                ),
                name="system_task_schedule_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="running")
                    | models.Q(last_started_at__isnull=False)
                ),
                name="system_task_running_started",
            ),
        ]
        indexes = [
            models.Index(
                fields=["enabled", "run_mode", "status"],
                name="system_task_schedule_idx",
            )
        ]

    def __str__(self):
        return self.name

    @property
    def due(self) -> bool:
        """Готово к автозапуску по интервалу."""
        if (
            not self.enabled
            or self.status == TaskJob.Status.RUNNING
            or self.run_mode != TaskJob.RunMode.SCHEDULED
        ):
            return False
        if not self.interval_minutes:
            return False
        if self.last_finished_at is None:
            return True
        delta = timedelta(minutes=self.interval_minutes)
        return timezone.now() >= self.last_finished_at + delta

    def run(self, user=None) -> "TaskRun":
        """Выполняет команду задания, фиксирует результат и события."""
        from apps.core.models import EventLog, log_event
        from apps.system.models import TaskRun
        from apps.system.tasks import run_command

        started_at = timezone.now()
        triggered_by = "user" if user is not None else "auto"
        claimed = (
            TaskJob.objects.filter(pk=self.pk)
            .exclude(status=TaskJob.Status.RUNNING)
            .update(status=TaskJob.Status.RUNNING, last_started_at=started_at)
        )
        if not claimed:
            raise TaskAlreadyRunning(f"Задание {self.pk} уже выполняется")
        self.status = TaskJob.Status.RUNNING
        self.last_started_at = started_at
        run = TaskRun.objects.create(
            task=self, triggered_by=triggered_by, started_at=started_at
        )
        event = log_event(
            module="system",
            event_type=EventLog.EventType.TASK,
            user=user,
            target=f"task:{self.pk}:{self.command}",
            pending=True,
        )
        try:
            log = run_command(self.command, self.params or {})
            ok = True
        except Exception as exc:  # noqa: BLE001 — любая ошибка задания фиксируется
            logger.exception("task %s failed", self.pk)
            log = f"{type(exc).__name__}: {exc}"
            ok = False

        finished_at = timezone.now()
        result = EventLog.Result.OK if ok else EventLog.Result.FAILED
        run.result = result
        run.started_at = started_at
        run.finished_at = finished_at
        run.log = log
        run.save()

        self.last_started_at = started_at
        self.last_finished_at = finished_at
        self.last_result = result
        self.last_log = log
        self.status = TaskJob.Status.COMPLETED if ok else TaskJob.Status.FAILED
        self.save(
            update_fields=[
                "status",
                "last_started_at",
                "last_finished_at",
                "last_result",
                "last_log",
            ]
        )

        log_event(
            module="system",
            event_type=EventLog.EventType.TASK,
            user=user,
            obj=event,
            result=result,
            detail=log[:2000],
            duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        )
        return run

    @classmethod
    def recover_stale(cls, *, stale_after_seconds: int | None = None) -> int:
        """Закрывает запуски, worker которых не завершился до таймаута."""
        from apps.core.models import EventLog, log_event

        timeout = (
            settings.TASK_STALE_AFTER_SECONDS
            if stale_after_seconds is None
            else stale_after_seconds
        )
        cutoff = timezone.now() - timedelta(seconds=max(timeout, 1))
        candidate_ids = cls.objects.filter(
            status=cls.Status.RUNNING,
            last_started_at__lt=cutoff,
        ).values_list("pk", flat=True)
        recovered = 0
        for task_id in candidate_ids:
            with transaction.atomic():
                task = cls.objects.select_for_update().get(pk=task_id)
                if task.status != cls.Status.RUNNING or not task.last_started_at:
                    continue
                if task.last_started_at >= cutoff:
                    continue
                finished_at = timezone.now()
                message = "Worker не завершил запуск до установленного таймаута."
                task.status = cls.Status.FAILED
                task.last_finished_at = finished_at
                task.last_result = EventLog.Result.FAILED
                task.last_log = message
                task.save(
                    update_fields=[
                        "status",
                        "last_finished_at",
                        "last_result",
                        "last_log",
                    ]
                )
                task.runs.filter(finished_at__isnull=True).update(
                    finished_at=finished_at,
                    result=EventLog.Result.FAILED,
                    log=message,
                )
                event = EventLog.objects.filter(
                    module="system",
                    event_type=EventLog.EventType.TASK,
                    target=f"task:{task.pk}:{task.command}",
                    finished_at__isnull=True,
                ).order_by("-started_at").first()
                if event:
                    log_event(
                        module="system",
                        event_type=EventLog.EventType.TASK,
                        obj=event,
                        result=EventLog.Result.FAILED,
                        detail=message,
                    )
                recovered += 1
        return recovered


class TaskRun(models.Model):
    """Запуск задания: время, инициатор, результат, лог."""

    task = models.ForeignKey(
        TaskJob, on_delete=models.CASCADE, related_name="runs", verbose_name="Задание"
    )
    triggered_by = models.CharField(
        max_length=16, default="user", verbose_name="Инициатор"
    )
    started_at = models.DateTimeField(verbose_name="Начало")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершение")
    result = models.CharField(
        max_length=16, blank=True, default="", verbose_name="Результат"
    )
    log = models.TextField(blank=True, default="", verbose_name="Лог")

    class Meta:
        verbose_name = "Запуск задания"
        verbose_name_plural = "Запуски заданий"
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.task_id} @ {self.started_at:%Y-%m-%d %H:%M}"


class TaskNote(models.Model):
    """Заметка к задаче (PRD v3 §2.11)."""

    task = models.ForeignKey(
        TaskJob, on_delete=models.CASCADE, related_name="notes", verbose_name="Задание"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Автор"
    )
    text = models.TextField(verbose_name="Текст")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Заметка к задаче"
        verbose_name_plural = "Заметки к задачам"
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:60]


class TaskFile(models.Model):
    """Файл-вложение к задаче (PRD v3 §2.11)."""

    def task_upload_to(self, filename):
        return f"tasks/{timezone.now():%Y/%m}/{filename}"

    task = models.ForeignKey(
        TaskJob, on_delete=models.CASCADE, related_name="files", verbose_name="Задание"
    )
    file = models.FileField(
        upload_to=task_upload_to,
        validators=[validate_attachment_file],
        verbose_name="Файл",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="Загрузил"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Загружено")

    class Meta:
        verbose_name = "Файл задачи"
        verbose_name_plural = "Файлы задач"
        ordering = ["-created_at"]

    def __str__(self):
        return self.file.name


@receiver(post_delete, sender=TaskFile)
def delete_task_file_after_commit(sender, instance, **kwargs):
    """Удаляет вложение после успешного удаления файла или самой задачи."""
    delete_field_file_after_commit(instance.file)


class TaskReport(models.Model):
    """Отчёт по задаче — результат выполнения (PRD v3 §2.11)."""

    task = models.ForeignKey(
        TaskJob, on_delete=models.CASCADE, related_name="reports", verbose_name="Задание"
    )
    title = models.CharField(max_length=200, verbose_name="Заголовок")
    content = models.TextField(verbose_name="Содержание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Отчёт по задаче"
        verbose_name_plural = "Отчёты по задачам"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class UserTableViewPref(models.Model):
    """Персональные настройки таблиц (ТЗ разд. 3.2)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="table_prefs",
        verbose_name="Пользователь",
    )
    table_key = models.CharField(max_length=32, verbose_name="Таблица")
    columns = models.JSONField(default=list, blank=True, verbose_name="Колонки (порядок)")
    sorting = models.JSONField(default=dict, blank=True, verbose_name="Сортировка")
    fixed_first = models.BooleanField(default=False, verbose_name="Фиксировать первую колонку")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Настройка таблицы"
        verbose_name_plural = "Настройки таблиц"
        constraints = [
            models.UniqueConstraint(fields=["user", "table_key"], name="uniq_user_table_pref"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.table_key}"

    @classmethod
    def for_table(cls, user, table_key: str, default_columns: list[str]) -> "UserTableViewPref":
        pref, _ = cls.objects.get_or_create(
            user=user, table_key=table_key, defaults={"columns": default_columns}
        )
        return pref
