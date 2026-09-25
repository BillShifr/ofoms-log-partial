from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("journal", "0012_irp_repeat_of")]

    operations = [
        migrations.AlterField(
            model_name="irptheme",
            name="title",
            field=models.CharField(max_length=2000, verbose_name="Название"),
        ),
    ]
