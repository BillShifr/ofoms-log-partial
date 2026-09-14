from django.db import migrations, models

import apps.journal.models
import apps.system.validators


class Migration(migrations.Migration):
    dependencies = [("journal", "0002_irpanswer_irpfile")]

    operations = [
        migrations.AlterField(
            model_name="irpfile",
            name="file",
            field=models.FileField(
                upload_to=apps.journal.models.irp_file_path,
                validators=[apps.system.validators.validate_document_file],
                verbose_name="Файл",
            ),
        ),
    ]
