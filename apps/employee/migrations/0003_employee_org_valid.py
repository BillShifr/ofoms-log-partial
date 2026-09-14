from django.db import migrations, models

VALID_ORGS = (81000, 81001, 81007, 81008)


def disable_unknown_organizations(apps, schema_editor):
    Employee = apps.get_model("employee", "Employee")
    Employee.objects.exclude(org__in=VALID_ORGS).update(org=81000, is_active=False)


class Migration(migrations.Migration):
    dependencies = [("employee", "0002_alter_employee_org")]

    operations = [
        migrations.RunPython(
            disable_unknown_organizations,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="employee",
            constraint=models.CheckConstraint(
                condition=models.Q(org__in=VALID_ORGS),
                name="employee_org_valid",
            ),
        ),
    ]
