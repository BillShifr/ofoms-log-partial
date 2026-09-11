import django.db.models.deletion
from django.db import migrations, models, transaction


def remove_orphan_attachments(apps, schema_editor):
    """Удаляет недоступные вложения; storage очищается только после commit БД."""
    MessageAttachment = apps.get_model("system", "MessageAttachment")
    for attachment in MessageAttachment.objects.filter(reply__isnull=True).iterator():
        field_file = attachment.file
        if field_file and field_file.name:
            storage = field_file.storage
            name = field_file.name
            transaction.on_commit(
                lambda storage=storage, name=name: storage.delete(name)
            )
        attachment.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("system", "0009_taskjob_system_task_command_valid_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_orphan_attachments, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="messageattachment",
            name="reply",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="attachments",
                to="system.messagereply",
                verbose_name="Сообщение",
            ),
        ),
    ]
