from django.db import migrations, models


def reject_blank_legacy_identity(apps, schema_editor):
    Irp = apps.get_model("journal", "Irp")
    invalid_ids = list(
        Irp.objects.filter(n_irp__regex=r"^\s*$")
        .order_by("pk")
        .values_list("pk", flat=True)[:20]
    )
    if invalid_ids:
        raise RuntimeError(
            "Найдены обращения без достоверного n_irp; исправьте записи перед "
            f"миграцией. ID: {invalid_ids}"
        )


class Migration(migrations.Migration):
    dependencies = [("journal", "0009_enforce_xml_provenance_constraints")]

    operations = [
        migrations.RunPython(
            reject_blank_legacy_identity,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="irp",
            constraint=models.CheckConstraint(
                condition=~models.Q(n_irp__regex=r"^\s*$"),
                name="irp_n_irp_not_blank",
            ),
        ),
    ]
