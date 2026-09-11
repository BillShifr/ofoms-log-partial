from django.db import migrations, models

VALID_STATUSES = (
    "registered",
    "in_progress",
    "redirected",
    "preliminary",
    "closed",
)


def normalize_legacy_irp(apps, schema_editor):
    Irp = apps.get_model("journal", "Irp")
    Irp.objects.exclude(status__in=VALID_STATUSES).update(status="registered")
    Irp.objects.filter(data_plan__lt=models.F("date_create")).update(
        data_plan=models.F("date_create")
    )
    Irp.objects.filter(date_close__lt=models.F("date_create")).update(
        date_close=models.F("date_create")
    )


class Migration(migrations.Migration):
    dependencies = [("journal", "0007_alter_irpfile_file")]

    operations = [
        migrations.RunPython(normalize_legacy_irp, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=VALID_STATUSES),
                name="irp_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=models.Q(data_plan__gte=models.F("date_create")),
                name="irp_plan_not_before_created",
            ),
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(date_close__isnull=True)
                    | models.Q(date_close__gte=models.F("date_create"))
                ),
                name="irp_close_not_before_created",
            ),
        ),
    ]
