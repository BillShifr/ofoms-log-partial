import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("journal", "0011_enforce_conditional_irp_details")]

    operations = [
        migrations.AddField(
            model_name="irp",
            name="repeat_of",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="repeat_appeals",
                to="journal.irp",
                verbose_name="Повторное обращение по",
            ),
        ),
    ]
