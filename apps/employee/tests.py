"""Тесты employee: модель Employee и GroupProxy."""

from types import SimpleNamespace

from apps.core.roles import ROLE_GROUP_MAP, ensure_role_groups
from apps.employee.admin import EmployeeAdmin, EmployeeChangeForm, RoleGroupAdmin
from apps.employee.models import Employee, GroupProxy
from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase

User = get_user_model()


class EmployeeModelTests(TestCase):
    def test_create_user(self):
        user = Employee.objects.create_user(
            username="operator1", password="GoodPass!1", org=81000
        )
        self.assertEqual(user.org, 81000)
        self.assertFalse(user.is_locked)
        self.assertEqual(user.failed_attempts, 0)

    def test_full_name(self):
        user = User.objects.create_user(
            username="nameuser", password="xYz123!@#", org=81001,
            last_name="Иванов", first_name="Пётр"
        )
        self.assertEqual(user.full_name(), "Иванов Пётр")

    def test_lock_mechanism(self):
        user = Employee.objects.create_user(
            username="locktest", password="Passw0rd!", org=81007
        )
        for _ in range(10):
            user.record_failed_login()
        user.refresh_from_db()
        self.assertTrue(user.is_locked)
        user.record_failed_login()
        self.assertEqual(user.failed_attempts, 10)
        self.assertIsNone(authenticate(username="locktest", password="Passw0rd!"))

    def test_unlock(self):
        user = Employee.objects.create_user(
            username="unlocktest", password="Passw0rd!", org=81008
        )
        user.record_failed_login()
        user.reset_failed_logins()
        self.assertFalse(user.is_locked)
        self.assertTrue(authenticate(username="unlocktest", password="Passw0rd!") is not None)

    def test_stale_instances_do_not_lose_failed_attempts(self):
        user = Employee.objects.create_user(
            username="atomic_lock", password="Passw0rd!", org=81000
        )
        first = Employee.objects.get(pk=user.pk)
        second = Employee.objects.get(pk=user.pk)

        first.record_failed_login()
        second.record_failed_login()

        user.refresh_from_db()
        self.assertEqual(user.failed_attempts, 2)

    def test_database_rejects_unknown_organization(self):
        user = Employee.objects.create_user(
            username="invalid_org", password="Passw0rd!", org=81000
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Employee.objects.filter(pk=user.pk).update(org=99999)

    def test_employee_admin_disables_physical_deletion(self):
        model_admin = admin.site._registry[Employee]

        self.assertFalse(model_admin.has_delete_permission(request=None))


class EmployeeAdminPolicyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_role_groups()

    def setUp(self):
        self.user = Employee.objects.create_user(
            username="admin_form_user",
            password="GoodPass!1",
            org=81000,
            is_staff=True,
        )
        self.admin_group = Group.objects.get(name="Администратор")
        self.user.groups.add(self.admin_group)

    def test_admin_form_only_offers_known_application_roles(self):
        Group.objects.create(name="Произвольная группа")

        form = EmployeeChangeForm(instance=self.user)

        self.assertEqual(
            set(form.fields["groups"].queryset.values_list("name", flat=True)),
            {
                "ОП1",
                "ОП2",
                "СП1",
                "СП2",
                "СП3",
                "Администратор",
                "Администратор контакт-центра",
            },
        )

    def test_admin_form_rejects_role_from_another_organization(self):
        smo_user = Employee.objects.create_user(
            username="smo_admin_form",
            password="GoodPass!1",
            org=81001,
        )
        form = EmployeeChangeForm(
            data={
                "username": smo_user.username,
                "org": str(smo_user.org),
                "groups": [self.admin_group.pk],
                "is_active": "on",
            },
            instance=smo_user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Роли не соответствуют", form.errors["groups"][0])

    def test_admin_makes_own_access_fields_read_only(self):
        model_admin = admin.site._registry[Employee]
        self.assertIsInstance(model_admin, EmployeeAdmin)
        request = SimpleNamespace(user=self.user)

        fields = model_admin.get_readonly_fields(request, self.user)

        self.assertTrue(
            {"is_active", "is_staff", "is_superuser", "groups", "user_permissions"}
            <= set(fields)
        )


class GroupProxyTests(TestCase):
    def test_proxy_model(self):
        GroupProxy.objects.get_or_create(name="Тестовая роль")
        self.assertTrue(GroupProxy.objects.filter(name="Тестовая роль").exists())

    def test_admin_lists_only_canonical_roles(self):
        ensure_role_groups()
        Group.objects.create(name="Произвольная группа")
        model_admin = admin.site._registry[GroupProxy]
        request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))

        names = set(model_admin.get_queryset(request).values_list("name", flat=True))

        self.assertIsInstance(model_admin, RoleGroupAdmin)
        self.assertEqual(names, set(ROLE_GROUP_MAP.values()))

    def test_admin_protects_role_identity_and_lifecycle(self):
        model_admin = admin.site._registry[GroupProxy]
        superuser_request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
        staff_request = SimpleNamespace(user=SimpleNamespace(is_superuser=False))

        self.assertIn("name", model_admin.get_readonly_fields(superuser_request))
        self.assertFalse(model_admin.has_add_permission(superuser_request))
        self.assertFalse(model_admin.has_delete_permission(superuser_request))
        self.assertTrue(model_admin.has_change_permission(superuser_request))
        self.assertFalse(model_admin.has_change_permission(staff_request))
