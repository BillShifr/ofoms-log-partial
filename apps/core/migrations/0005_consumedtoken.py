from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0004_eventlog_core_event_started_idx_and_more")]

    operations = [
        migrations.CreateModel(
            name="ConsumedToken",
            fields=[
                (
                    "jti",
                    models.UUIDField(editable=False, primary_key=True, serialize=False),
                ),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Использованный временный токен",
                "verbose_name_plural": "Использованные временные токены",
            },
        ),
    ]
