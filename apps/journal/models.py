"""Модуль «journal»: журнал обращений граждан.

Перенос моделей из v1 (journal.portal.tfoms) без потери данных, кроме
выгладившего поля db_column (новая БД). Сохранены коды справочников
(IRP_TYPES, IRP_WAYS, IRP_HOW, LINES, RESULTS и т.д.) для совместимости
с файлами обмена и статистическими отчётами.
"""

from django.core.exceptions import ValidationError
from django.db import models

from apps.employee.models import ORGS, Employee
from apps.system.validators import validate_document_file

# ---------------------------------------------------------------------------
# Справочники (коды закреплены форматом обмена, МИС/реестрами)
# ---------------------------------------------------------------------------
IRP_TYPES = (
    (1, "Консультация"),
    (2, "Жалоба"),
    (3, "Предложение"),
    (4, "Заявление"),
    (5, "вопросы, не относящиеся к сфере ОМС"),
)

IRP_WAYS = (
    (1, "Напрямую от заявителя"),
    (2, "ФОМС"),
    (3, "Иной федеральный орган исполнительной власти"),
    (4, "Территориальный орган исполнительной власти"),
    (5, "Иная организация"),
    (6, "Контакт-центр Минздрава России"),
)

IRP_HOW = (
    (1, "По телефону горячей линии"),
    (2, "По сети Интернет"),
    (3, "Личное письменное обращение"),
    (4, "Личный прием (устное)"),
    (5, "Почтовым сообщением"),
)

ZH_TYPES = (
    ("1", "Обоснованная"),
    ("1.1", "Обоснованная, удовлетворенная в досудебном порядке"),
    ("1.2", "Обоснованная, удовлетворенная в судебном порядке"),
    ("2", "Необоснованная"),
)

OTV_T = (
    (1, "ТФОМС"),
    (2, "СМО"),
    (3, "ТФОМС (аутсорсинг)"),
    (4, "СМО (аутсорсинг)"),
    (5, "МО"),
    (6, "ОИВ субъекта РФ"),
    (7, " МО (аутсорсинг)"),
    (8, "ОИВ субъекта РФ (аутсорсинг)"),
)

RESULTS = (
    (1, "Дана консультация"),
    (2, "Рассмотрено обращение"),
    (3, "Заявление удовлетворено"),
    (4, "Заявление не удовлетворено"),
    (5, "Рассмотрена жалоба"),
    (6, "Звонок переадресован"),
    (7, "Обращение переадресовано в другую организацию"),
    (8, "Рассмотрено предложение"),
)

LINES = (
    (1, "ОП1"),
    (2, "ОП2"),
    (3, "СП1"),
    (4, "СП2"),
    (5, "СП3"),
    (6, "Администратор (или иной сотрудник ТФОМС)"),
)

DOC_TYPES = (
    (1, "Паспорт гражданина СССР"),
    (2, "Загранпаспорт гражданина СССР"),
    (3, "Свидетельство о рождении"),
    (4, "Удостоверение личности офицера"),
    (5, "Справка об освобождении из места лишения свободы"),
    (6, "Паспорт Минморфлота"),
    (7, "Военный билет"),
    (8, "Дипломатический паспорт гражданина Российской Федерации"),
    (9, "Иностранный паспорт"),
    (10, "Свидетельство о регистрации ходатайства о признании иммигранта беженцем"),
    (11, "Вид на жительство"),
    (12, "Удостоверение беженца в Российской Федерации"),
    (13, "Временное удостоверение личности гражданина Российской Федерации"),
    (14, "Паспорт гражданина Российской Федерации"),
    (15, "Заграничный паспорт гражданина Российской Федерации"),
    (16, "Паспорт моряка"),
    (17, "Военный билет офицера запаса"),
    (18, "Иные документы, выдаваемые органами Министерства внутренних дел"),
    (21, "Документ иностранного гражданина"),
    (22, "Документ лица без гражданства"),
    (23, "Разрешение на временное проживание"),
    (24, "Свидетельство о рождении, выданное не в Российской Федерации"),
    (25, "Свидетельство о предоставлении временного убежища на территории РФ"),
    (26, "Удостоверение сотрудника Евразийской экономической комиссии"),
    (27, "Копия жалобы о лишении статуса беженца"),
    (
        28,
        "Иной документ,соотв. свидетельству о предоставлении убежища на территории РФ",
    ),
)

PR_OUT = (
    (1, "обращение (запрос) направлено в МО субъекта РФ"),
    (2, "обращение (запрос) направлено в ОИВ субъекта РФ"),
    (3, "обращение (запрос) направлено в иную СМО субъекта РФ"),
    (4, "обращение (запрос) направлено в организацию другого субъекта РФ"),
)


class XmlFiles(models.Model):
    """Файл, из которого импортированы обращения (обмен по Приложению №10)."""

    version = models.CharField(max_length=10, null=True, blank=True, verbose_name="Версия файла")
    data = models.DateField(null=True, blank=True, verbose_name="Дата формирования файла")
    year = models.CharField(max_length=4, verbose_name="Отчетный год")
    month = models.CharField(max_length=2, verbose_name="Отчетный месяц")
    day = models.CharField(max_length=2, verbose_name="День")
    time = models.TimeField(null=True, blank=True, verbose_name="Время")
    smo = models.IntegerField(choices=ORGS, verbose_name="СМО")
    filename = models.CharField(max_length=200, verbose_name="Имя файла")
    real_filename = models.CharField(max_length=200, verbose_name="Имя файла на диске")

    class Meta:
        verbose_name = "Файл с обращениями"
        verbose_name_plural = "Файлы с обращениями"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.filename}"

    @property
    def storage_date(self) -> str:
        return str(self.data)


class IrpTheme(models.Model):
    """Тема обращения. Версионируемый справочник (актуальна версия 3)."""

    code_name = models.CharField("Код темы", max_length=14)
    title = models.CharField(max_length=255, verbose_name="Название")
    version = models.IntegerField("Версия справочника", default=1)

    class Meta:
        ordering = ["-version", "code_name"]
        unique_together = ["code_name", "version"]
        verbose_name = "Тема обращения"
        verbose_name_plural = "Темы обращения"

    def __str__(self) -> str:
        return f"{self.code_name} - {self.title}"


class Irp(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Зарегистрировано"
        IN_PROGRESS = "in_progress", "В работе"
        REDIRECTED = "redirected", "Переадресовано"
        PRELIMINARY = "preliminary", "Предварительный ответ"
        CLOSED = "closed", "Закрыто"

    """Обращение гражданина (запись журнала)."""

    input_file = models.ForeignKey(
        XmlFiles,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Файл импорта",
        on_delete=models.PROTECT,
    )
    n_irp = models.CharField(
        max_length=36, unique=True, verbose_name="Уникальный номер обращения"
    )
    tf_id = models.UUIDField(null=True, blank=True, verbose_name="Идентификатор в ТФОМС")
    irp_type = models.SmallIntegerField(choices=IRP_TYPES, verbose_name="Вид обращения")
    date_create = models.DateField(verbose_name="Дата поступления")
    time_create = models.TimeField(blank=True, null=True, verbose_name="Время поступления")
    way = models.SmallIntegerField(choices=IRP_WAYS, verbose_name="Источник поступления")
    way_n = models.CharField(
        max_length=250, null=True, blank=True, verbose_name="Организация-источник"
    )
    how = models.SmallIntegerField(choices=IRP_HOW, verbose_name="Способ обращения")
    theme = models.ForeignKey(
        IrpTheme, on_delete=models.PROTECT, verbose_name="Тема обращения"
    )
    theme_comment = models.CharField(
        max_length=500, blank=True, null=True, verbose_name="Комментарий к теме"
    )
    text = models.TextField(
        max_length=1000, blank=True, null=True, verbose_name="Содержание обращения"
    )
    zh_d = models.CharField(
        max_length=10, blank=True, null=True, choices=ZH_TYPES, verbose_name="Сведения о жалобе"
    )
    otv_t = models.SmallIntegerField(
        choices=OTV_T, verbose_name="Тип организации, ответственной за обращение"
    )
    otv_kon = models.IntegerField(
        choices=ORGS, verbose_name="Организация, ответственная за обращение"
    )
    employee_one = models.ForeignKey(
        Employee,
        related_name="employee_1",
        verbose_name="Сотрудник, принявший обращение",
        on_delete=models.PROTECT,
    )
    line_one = models.SmallIntegerField(
        blank=True, null=True, choices=LINES, verbose_name="Линия принятия"
    )
    employee_it = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        related_name="employee_it",
        on_delete=models.PROTECT,
        verbose_name="Сотрудник, ответственный за обращение",
    )
    line_it = models.SmallIntegerField(
        blank=True, null=True, choices=LINES, verbose_name="Линия рассмотрения"
    )
    data_plan = models.DateField(verbose_name="Дата окончания срока рассмотрения")
    date_close = models.DateField(null=True, blank=True, verbose_name="Дата закрытия")
    result = models.SmallIntegerField(
        blank=True, null=True, choices=RESULTS, verbose_name="Исход обращения"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.REGISTERED,
        db_index=True,
        verbose_name="Статус",
    )

    # ---- Заявитель (z_*) ----
    z_f = models.CharField(max_length=40, blank=True, null=True, verbose_name="Фамилия")
    z_i = models.CharField(max_length=40, blank=True, null=True, verbose_name="Имя")
    z_o = models.CharField(max_length=40, blank=True, null=True, verbose_name="Отчество")
    z_dr = models.DateField(blank=True, null=True, verbose_name="Дата рождения")
    z_enp = models.CharField(max_length=16, blank=True, null=True, verbose_name="ЕНП")
    z_smo = models.IntegerField(
        blank=True, null=True, choices=ORGS, verbose_name="Страховая принадлежность"
    )
    z_doctype = models.SmallIntegerField(
        blank=True, null=True, choices=DOC_TYPES,
        verbose_name="Тип документа, удостоверяющего личность",
    )
    z_docser = models.CharField(max_length=10, blank=True, null=True, verbose_name="Серия")
    z_docnum = models.CharField(max_length=20, blank=True, null=True, verbose_name="Номер")
    adr = models.CharField(max_length=120, blank=True, null=True, verbose_name="Адрес заявителя")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Телефон")
    e_mail = models.CharField(
        max_length=200, blank=True, null=True, verbose_name="E-mail заявителя"
    )

    # ---- Застрахованный (in_*) ----
    in_f = models.CharField(max_length=40, blank=True, null=True, verbose_name="Фамилия")
    in_i = models.CharField(max_length=40, blank=True, null=True, verbose_name="Имя")
    in_o = models.CharField(max_length=40, blank=True, null=True, verbose_name="Отчество")
    in_dr = models.DateField(blank=True, null=True, verbose_name="Дата рождения")
    in_enp = models.CharField(max_length=16, blank=True, null=True, verbose_name="ЕНП")
    in_smo = models.IntegerField(
        blank=True, null=True, choices=ORGS, verbose_name="Страховая принадлежность"
    )
    in_doctype = models.SmallIntegerField(
        blank=True, null=True, choices=DOC_TYPES,
        verbose_name="Тип документа, удостоверяющего личность",
    )
    in_docser = models.CharField(max_length=10, blank=True, null=True, verbose_name="Серия")
    in_docnum = models.CharField(max_length=20, blank=True, null=True, verbose_name="Номер")

    # ---- Переадресация (Приложение №10: date_cross/time_cross, pr_out) ----
    pr_out = models.SmallIntegerField(
        blank=True, null=True, choices=PR_OUT, verbose_name="Признак направления"
    )
    date_cross = models.DateField(blank=True, null=True, verbose_name="Дата направления")
    time_cross = models.TimeField(blank=True, null=True, verbose_name="Время направления")

    class Meta:
        verbose_name = "Обращение"
        verbose_name_plural = "Обращения"
        ordering = ["-date_create", "-id"]
        indexes = [
            models.Index(fields=["date_create", "id"], name="journal_date_id_idx"),
            models.Index(fields=["date_close", "data_plan"], name="journal_close_plan_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="closed",
                        date_close__isnull=False,
                        result__isnull=False,
                    )
                    | (
                        ~models.Q(status="closed")
                        & models.Q(date_close__isnull=True, result__isnull=True)
                    )
                ),
                name="irp_closed_status_has_date_and_result",
            )
        ]

    def __str__(self) -> str:
        return self.n_irp

    def clean(self):
        super().clean()
        if self.way == 5 and not self.way_n:
            raise ValidationError({"way_n": "Укажите организацию"})
        if bool(self.date_close) != bool(self.result):
            raise ValidationError(
                "Для закрытия обращения одновременно укажите дату и исход."
            )
        if self.date_close and self.date_create and self.date_close < self.date_create:
            raise ValidationError(
                {"date_close": "Дата закрытия не может быть раньше даты поступления."}
            )
        if self.status == self.Status.CLOSED and not self.date_close:
            raise ValidationError(
                {"date_close": "Для статуса «Закрыто» укажите дату и исход."}
            )

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED

    def can_transition_to(self, target: str) -> bool:
        allowed = {
            self.Status.REGISTERED: {
                self.Status.IN_PROGRESS,
                self.Status.REDIRECTED,
                self.Status.PRELIMINARY,
                self.Status.CLOSED,
            },
            self.Status.IN_PROGRESS: {
                self.Status.REDIRECTED,
                self.Status.PRELIMINARY,
                self.Status.CLOSED,
            },
            self.Status.REDIRECTED: {
                self.Status.PRELIMINARY,
                self.Status.CLOSED,
            },
            self.Status.PRELIMINARY: {
                self.Status.PRELIMINARY,
                self.Status.CLOSED,
            },
            self.Status.CLOSED: set(),
        }
        return target == self.status or target in allowed[self.status]

    def synchronize_imported_status(self) -> None:
        """Восстанавливает lifecycle для импорта, не открывая закрытые записи."""
        if self.date_close and self.result:
            target = self.Status.CLOSED
        elif self.pk and self.answers.filter(is_preliminary=True).exists():
            target = self.Status.PRELIMINARY
        elif self.date_cross or self.pr_out:
            target = self.Status.REDIRECTED
        else:
            target = self.Status.REGISTERED
        if self.pk and self.status == self.Status.CLOSED and target != self.Status.CLOSED:
            raise ValidationError(
                {"status": "Пакетный импорт не может повторно открыть обращение."}
            )
        self.status = target

    @property
    def is_overdue(self) -> bool:
        """Просрочено: не закрыто, а плановая дата уже прошла."""
        import datetime

        if self.date_close:
            return False
        return bool(self.data_plan) and self.data_plan < datetime.date.today()


class IrpHistory(models.Model):
    """История изменения обращения (ТЗ разд. 2.3)."""

    irp = models.ForeignKey(Irp, related_name="history", on_delete=models.CASCADE)
    user = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Кем изменено"
    )
    field_name = models.CharField(max_length=64, verbose_name="Поле")
    old_value = models.TextField(blank=True, null=True, verbose_name="Было")
    new_value = models.TextField(blank=True, null=True, verbose_name="Стало")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда изменено")

    class Meta:
        verbose_name = "Запись истории"
        verbose_name_plural = "История изменений"
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.irp.n_irp}: {self.field_name}"


class IrpAnswer(models.Model):
    """Ответ на обращение (ТЗ п. 215: предварительный ответ с признаком).

    Допускается несколько ответов; предварительные помечаются признаком,
    итоговый фиксируется при закрытии обращения (date_close/result в Irp).
    """

    irp = models.ForeignKey(
        Irp, related_name="answers", on_delete=models.CASCADE, verbose_name="Обращение"
    )
    user = models.ForeignKey(
        Employee, on_delete=models.PROTECT, verbose_name="Кто подготовил"
    )
    text = models.TextField(verbose_name="Текст ответа")
    is_preliminary = models.BooleanField(
        default=True, verbose_name="Предварительный ответ"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда")

    class Meta:
        verbose_name = "Ответ"
        verbose_name_plural = "Ответы"
        ordering = ["created_at"]

    def __str__(self) -> str:
        kind = "предварительный" if self.is_preliminary else "итоговый"
        return f"{self.irp.n_irp}: {kind} ответ"


def irp_file_path(instance, filename):
    """media/journal/<irp_id>/<filename>"""
    return f"journal/{instance.irp_id}/{filename}"


class IrpFile(models.Model):
    """Файл, прикреплённый к обращению или к ответу (ТЗ п. 200)."""

    irp = models.ForeignKey(
        Irp, related_name="files", on_delete=models.CASCADE, verbose_name="Обращение"
    )
    answer = models.ForeignKey(
        IrpAnswer,
        null=True, blank=True, related_name="files",
        on_delete=models.CASCADE, verbose_name="Ответ",
    )
    file = models.FileField(
        upload_to=irp_file_path,
        validators=[validate_document_file],
        verbose_name="Файл",
    )
    uploader = models.ForeignKey(
        Employee, on_delete=models.PROTECT, verbose_name="Загрузил"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда")

    class Meta:
        verbose_name = "Файл"
        verbose_name_plural = "Файлы"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.irp.n_irp}: {self.file.name}"
