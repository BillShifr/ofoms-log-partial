from django.db import migrations, models


def derive_status(apps, schema_editor):
    Irp = apps.get_model("journal", "Irp")
    for irp in Irp.objects.all().iterator():
        if irp.date_close:
            status = "closed"
        elif irp.answers.filter(is_preliminary=True).exists():
            status = "preliminary"
        elif irp.date_cross or irp.pr_out:
            status = "redirected"
        else:
            status = "registered"
        Irp.objects.filter(pk=irp.pk).update(status=status)


class Migration(migrations.Migration):
    dependencies = [("journal", "0003_validate_irpfile_uploads")]

    operations = [
        migrations.AddField(
            model_name="irp",
            name="status",
            field=models.CharField(
                choices=[
                    ("registered", "Зарегистрировано"),
                    ("in_progress", "В работе"),
                    ("redirected", "Переадресовано"),
                    ("preliminary", "Предварительный ответ"),
                    ("closed", "Закрыто"),
                ],
                db_index=True,
                default="registered",
                max_length=16,
                verbose_name="Статус",
            ),
        ),
        migrations.RunPython(derive_status, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
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
            ),
        ),
    ]
