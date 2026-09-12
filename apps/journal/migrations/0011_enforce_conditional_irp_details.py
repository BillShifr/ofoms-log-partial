from django.db import migrations, models


def reject_inconsistent_legacy_details(apps, schema_editor):
    Irp = apps.get_model("journal", "Irp")
    invalid = Irp.objects.filter(
        models.Q(zh_d__isnull=False) & ~models.Q(zh_d="") & ~models.Q(irp_type=2)
        | models.Q(pr_out__isnull=True)
        & (models.Q(date_cross__isnull=False) | models.Q(time_cross__isnull=False))
        | models.Q(time_cross__isnull=False, date_cross__isnull=True)
    )
    invalid_ids = list(invalid.order_by("pk").values_list("pk", flat=True)[:20])
    if invalid_ids:
        raise RuntimeError(
            "Найдены обращения с противоречивыми условными реквизитами; "
            f"исправьте записи перед миграцией. ID: {invalid_ids}"
        )


class Migration(migrations.Migration):
    dependencies = [("journal", "0010_enforce_irp_identity")]

    operations = [
        migrations.RunPython(
            reject_inconsistent_legacy_details,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(irp_type=2)
                    | models.Q(zh_d__isnull=True)
                    | models.Q(zh_d="")
                ),
                name="irp_complaint_details_match_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(pr_out__isnull=False)
                    | models.Q(date_cross__isnull=True, time_cross__isnull=True)
                ),
                name="irp_redirect_details_match_flag",
            ),
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(time_cross__isnull=True)
                    | models.Q(date_cross__isnull=False)
                ),
                name="irp_redirect_time_has_date",
            ),
        ),
    ]
