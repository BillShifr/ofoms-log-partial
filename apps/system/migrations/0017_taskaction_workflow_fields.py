from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("system", "0016_custom_task_actions"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskaction",
            name="action_type",
            field=models.CharField(
                choices=[
                    ("manual", "Ручное действие"),
                    ("close_appeals", "Закрыть обращения по условиям"),
                ],
                default="manual",
                max_length=24,
                verbose_name="Тип сценария",
            ),
        ),
        migrations.AddField(
            model_name="taskaction",
            name="condition_logic",
            field=models.CharField(
                choices=[("all", "Все условия"), ("any", "Любое условие")],
                default="all",
                max_length=8,
                verbose_name="Как применять условия",
            ),
        ),
        migrations.AddField(
            model_name="taskaction",
            name="condition_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("open", "Открытые"),
                    ("overdue", "Просроченные"),
                    ("preliminary", "С предварительным ответом"),
                ],
                default="",
                max_length=24,
                verbose_name="Статус обращений",
            ),
        ),
        migrations.AddField(
            model_name="taskaction",
            name="condition_org",
            field=models.IntegerField(
                blank=True,
                choices=[
                    (81000, "ТФОМС"),
                    (81001, "СОГАЗ - МЕД"),
                    (81007, "Капитал МС"),
                    (81008, "АльфаСтрахование - ОМС"),
                ],
                null=True,
                verbose_name="Организация обращений",
            ),
        ),
        migrations.AddField(
            model_name="taskaction",
            name="close_result",
            field=models.SmallIntegerField(
                blank=True,
                choices=[
                    (1, "Дана консультация"),
                    (2, "Рассмотрено обращение"),
                    (3, "Заявление удовлетворено"),
                    (4, "Заявление не удовлетворено"),
                    (5, "Рассмотрена жалоба"),
                    (6, "Звонок переадресован"),
                    (7, "Обращение переадресовано в другую организацию"),
                    (8, "Рассмотрено предложение"),
                ],
                null=True,
                verbose_name="Исход при закрытии",
            ),
        ),
    ]
