from django.db import migrations, models

import apps.system.models
import apps.system.validators


class Migration(migrations.Migration):
    dependencies = [("system", "0004_newscategory_alter_newsitem_options_and_more")]

    operations = [
        migrations.AlterField(
            model_name="taskfile",
            name="file",
            field=models.FileField(
                upload_to=apps.system.models.TaskFile.task_upload_to,
                validators=[apps.system.validators.validate_document_file],
                verbose_name="Файл",
            ),
        ),
    ]
