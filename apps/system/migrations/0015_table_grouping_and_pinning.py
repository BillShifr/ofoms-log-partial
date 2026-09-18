from django.db import migrations, models


def migrate_fixed_first(apps, schema_editor):
    UserTableViewPref = apps.get_model("system", "UserTableViewPref")
    for pref in UserTableViewPref.objects.filter(fixed_first=True).iterator():
        columns = pref.columns or []
        if columns:
            pref.pinned_columns = [columns[0]]
            pref.save(update_fields=["pinned_columns"])


class Migration(migrations.Migration):
    dependencies = [("system", "0014_task_queue_and_real_actions")]

    operations = [
        migrations.AddField(
            model_name="usertableviewpref",
            name="grouped_headers",
            field=models.JSONField(
                blank=True, default=list, verbose_name="Групповые заголовки"
            ),
        ),
        migrations.AddField(
            model_name="usertableviewpref",
            name="pinned_columns",
            field=models.JSONField(
                blank=True, default=list, verbose_name="Закреплённые колонки"
            ),
        ),
        migrations.RunPython(migrate_fixed_first, migrations.RunPython.noop),
    ]
