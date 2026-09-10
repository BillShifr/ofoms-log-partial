"""Создание групп-ролей RBAC (письмо ФФОМС п. 10–16)."""

from django.db import migrations

ROLE_GROUP_NAMES = [
    "ОП1",
    "ОП2",
    "СП1",
    "СП2",
    "СП3",
    "Администратор",
    "Администратор контакт-центра",
]


def create_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_GROUP_NAMES:
        Group.objects.get_or_create(name=name)


def drop_role_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_GROUP_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(create_role_groups, drop_role_groups),
    ]
