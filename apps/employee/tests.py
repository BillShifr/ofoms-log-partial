"""Тесты employee: модель Employee и GroupProxy."""

from types import SimpleNamespace
from unittest.mock import patch

from apps.core.models import EventLog
from apps.core.roles import ROLE_GROUP_MAP, ensure_role_groups
from apps.employee.admin import (
    EmployeeAdmin,
    EmployeeChangeForm,
    RoleGroupAdmin,
    unlock_accounts,
)
from apps.employee.models import Employee, GroupProxy
from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

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

    def test_non_tfoms_staff_is_confined_to_own_organization_in_admin(self):
        actor = Employee.objects.create_user(
            username="smo_delegated_employee_admin",
            password="GoodPass!1",
            org=81001,
            is_staff=True,
        )
        actor.user_permissions.set(
            Permission.objects.filter(
                codename__in=("add_employee", "change_employee", "view_employee")
            )
        )
        own = Employee.objects.create_user(
            username="smo_own_employee",
            password="GoodPass!1",
            org=81001,
        )
        foreign = Employee.objects.create_user(
            username="smo_foreign_employee",
            password="GoodPass!1",
            org=81007,
        )
        root = Employee.objects.create_superuser(
            username="smo_hidden_root",
            password="GoodPass!1",
            org=81001,
        )
        request = SimpleNamespace(user=actor)
        model_admin = admin.site._registry[Employee]

        visible_ids = set(
            model_admin.get_queryset(request).values_list("pk", flat=True)
        )

        self.assertIn(actor.pk, visible_ids)
        self.assertIn(own.pk, visible_ids)
        self.assertNotIn(foreign.pk, visible_ids)
        self.assertNotIn(root.pk, visible_ids)
        self.assertTrue(model_admin.has_change_permission(request, own))
        self.assertFalse(model_admin.has_change_permission(request, foreign))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertIn("org", model_admin.get_readonly_fields(request, own))

    def test_non_tfoms_staff_cannot_move_employee_to_foreign_organization(self):
        actor = Employee.objects.create_user(
            username="smo_employee_admin_move_actor",
            password="GoodPass!1",
            org=81001,
            is_staff=True,
        )
        actor.user_permissions.set(
            Permission.objects.filter(
                codename__in=("change_employee", "view_employee")
            )
        )
        target = Employee.objects.create_user(
            username="smo_employee_move_target",
            password="GoodPass!1",
            org=81001,
        )
        target.groups.add(Group.objects.get(name="СП1"))
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:employee_employee_change", args=[target.pk]),
            {
                "username": target.username,
                "last_name": "Остался в СМО",
                "first_name": "",
                "email": "",
                "org": "81007",
                "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                "is_active": "on",
                "groups": list(target.groups.values_list("pk", flat=True)),
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertEqual(target.org, 81001)
        self.assertEqual(target.last_name, "Остался в СМО")

    def test_tfoms_staff_retains_cross_organization_employee_management(self):
        actor = Employee.objects.create_user(
            username="tfoms_delegated_employee_admin",
            password="GoodPass!1",
            org=81000,
            is_staff=True,
        )
        actor.user_permissions.set(
            Permission.objects.filter(
                codename__in=("add_employee", "change_employee", "view_employee")
            )
        )
        foreign = Employee.objects.create_user(
            username="tfoms_managed_foreign_employee",
            password="GoodPass!1",
            org=81007,
        )
        request = SimpleNamespace(user=actor)
        model_admin = admin.site._registry[Employee]

        visible_ids = set(
            model_admin.get_queryset(request).values_list("pk", flat=True)
        )

        self.assertIn(foreign.pk, visible_ids)
        self.assertTrue(model_admin.has_change_permission(request, foreign))
        self.assertTrue(model_admin.has_add_permission(request))
        self.assertNotIn("org", model_admin.get_readonly_fields(request, foreign))

    def test_non_superuser_admin_cannot_grant_superuser_or_direct_permissions(self):
        actor = Employee.objects.create_user(
            username="limited_employee_admin",
            password="GoodPass!1",
            org=81000,
            is_staff=True,
        )
        employee_permissions = Permission.objects.filter(
            codename__in=("view_employee", "change_employee")
        )
        actor.user_permissions.set(employee_permissions)
        target = Employee.objects.create_user(
            username="no_privilege_escalation_target",
            password="GoodPass!1",
            org=81000,
        )
        unrelated_permission = Permission.objects.exclude(
            pk__in=employee_permissions.values_list("pk", flat=True)
        ).order_by("pk").first()
        model_admin = admin.site._registry[Employee]
        readonly = model_admin.get_readonly_fields(
            SimpleNamespace(user=actor), target
        )
        self.assertIn("is_superuser", readonly)
        self.assertIn("user_permissions", readonly)
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:employee_employee_change", args=[target.pk]),
            {
                "username": target.username,
                "last_name": "",
                "first_name": "",
                "email": "",
                "org": "81000",
                "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                "is_active": "on",
                "is_superuser": "on",
                "user_permissions": [unrelated_permission.pk],
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_superuser)
        self.assertFalse(target.user_permissions.exists())

    def test_superuser_can_manage_privilege_fields_for_another_account(self):
        actor = Employee.objects.create_superuser(
            username="superuser_readonly_policy_actor",
            password="GoodPass!1",
            org=81000,
        )
        target = Employee.objects.create_user(
            username="superuser_readonly_policy_target",
            password="GoodPass!1",
            org=81000,
        )
        readonly = admin.site._registry[Employee].get_readonly_fields(
            SimpleNamespace(user=actor), target
        )

        self.assertNotIn("is_superuser", readonly)
        self.assertNotIn("user_permissions", readonly)

    def test_admin_password_change_records_subject_audit(self):
        actor = Employee.objects.create_superuser(
            username="password_admin_actor",
            password="GoodPass!1",
            org=81000,
        )
        target = Employee.objects.create_user(
            username="password_admin_target",
            password="OldGoodPass!1",
            org=81000,
        )
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[target.pk]),
            {
                "password1": "Zebra!4827Orbit",
                "password2": "Zebra!4827Orbit",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.check_password("Zebra!4827Orbit"))
        event = EventLog.objects.get(
            target=f"admin:employee:{target.pk}:password"
        )
        self.assertEqual(event.event_type, EventLog.EventType.UPDATE)
        self.assertEqual(event.user, actor)

    def test_admin_password_change_rolls_back_when_audit_fails(self):
        actor = Employee.objects.create_superuser(
            username="password_admin_rollback_actor",
            password="GoodPass!1",
            org=81000,
        )
        target = Employee.objects.create_user(
            username="password_admin_rollback_target",
            password="OriginalGoodPass!1",
            org=81000,
        )
        self.client.force_login(actor)

        with (
            patch("apps.employee.admin.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("admin:auth_user_password_change", args=[target.pk]),
                {
                    "password1": "Quartz!5938River",
                    "password2": "Quartz!5938River",
                },
            )

        target.refresh_from_db()
        self.assertTrue(target.check_password("OriginalGoodPass!1"))
        self.assertFalse(target.check_password("Quartz!5938River"))

    def test_non_superuser_admin_cannot_reset_another_password(self):
        actor = Employee.objects.create_user(
            username="limited_password_admin",
            password="GoodPass!1",
            org=81000,
            is_staff=True,
        )
        actor.user_permissions.set(
            Permission.objects.filter(
                codename__in=("view_employee", "change_employee")
            )
        )
        target = Employee.objects.create_superuser(
            username="protected_password_target",
            password="ProtectedGoodPass!1",
            org=81000,
        )
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[target.pk]),
            {
                "password1": "Hijacked!4827Orbit",
                "password2": "Hijacked!4827Orbit",
            },
        )

        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertTrue(target.check_password("ProtectedGoodPass!1"))
        self.assertFalse(target.check_password("Hijacked!4827Orbit"))
        self.assertFalse(
            EventLog.objects.filter(
                target=f"admin:employee:{target.pk}:password"
            ).exists()
        )

    def test_non_superuser_admin_cannot_list_or_change_superuser_account(self):
        actor = Employee.objects.create_user(
            username="limited_profile_admin",
            password="GoodPass!1",
            org=81000,
            is_staff=True,
        )
        actor.user_permissions.set(
            Permission.objects.filter(
                codename__in=("view_employee", "change_employee")
            )
        )
        target = Employee.objects.create_superuser(
            username="protected_profile_superuser",
            password="ProtectedGoodPass!1",
            org=81000,
        )
        self.assertFalse(
            admin.site._registry[Employee].has_change_permission(
                SimpleNamespace(user=actor), target
            )
        )
        self.client.force_login(actor)

        listing = self.client.get(reverse("admin:employee_employee_changelist"))
        response = self.client.post(
            reverse("admin:employee_employee_change", args=[target.pk]),
            {
                "username": target.username,
                "last_name": "Подмена",
                "first_name": "",
                "email": "",
                "org": "81000",
                "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                "_save": "Сохранить",
            },
        )

        self.assertEqual(listing.status_code, 200)
        self.assertNotContains(listing, target.username)
        self.assertIn(response.status_code, (302, 404))
        target.refresh_from_db()
        self.assertEqual(target.last_name, "")
        self.assertTrue(target.is_active)
        self.assertTrue(target.is_staff)
        self.assertTrue(target.is_superuser)

    def test_admin_change_records_subject_audit_after_roles(self):
        actor = Employee.objects.create_superuser(
            username="employee_admin_actor",
            password="GoodPass!1",
            org=81000,
        )
        target = Employee.objects.create_user(
            username="employee_admin_target",
            password="GoodPass!1",
            org=81000,
            last_name="До",
        )
        operator_group = Group.objects.get(name="ОП1")
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:employee_employee_change", args=[target.pk]),
            {
                "username": target.username,
                "last_name": "После",
                "first_name": "",
                "email": "",
                "org": "81000",
                "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                "is_active": "on",
                "groups": [operator_group.pk],
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertEqual(target.last_name, "После")
        self.assertTrue(target.groups.filter(pk=operator_group.pk).exists())
        event = EventLog.objects.get(target=f"admin:employee:{target.pk}:update")
        self.assertEqual(event.event_type, EventLog.EventType.UPDATE)
        self.assertEqual(event.user, actor)

    def test_admin_create_records_subject_audit(self):
        actor = Employee.objects.create_superuser(
            username="employee_admin_create_actor",
            password="GoodPass!1",
            org=81000,
        )
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:employee_employee_add"),
            {
                "username": "employee_created_in_admin",
                "password1": "AnotherGoodPass!2",
                "password2": "AnotherGoodPass!2",
                "org": "81000",
                "_save": "Сохранить",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = Employee.objects.get(username="employee_created_in_admin")
        event = EventLog.objects.get(target=f"admin:employee:{created.pk}:create")
        self.assertEqual(event.event_type, EventLog.EventType.CREATE)
        self.assertEqual(event.user, actor)

    def test_admin_change_rolls_back_fields_and_roles_when_audit_fails(self):
        actor = Employee.objects.create_superuser(
            username="employee_admin_rollback_actor",
            password="GoodPass!1",
            org=81000,
        )
        target = Employee.objects.create_user(
            username="employee_admin_rollback_target",
            password="GoodPass!1",
            org=81000,
            last_name="Исходное",
        )
        operator_group = Group.objects.get(name="ОП1")
        self.client.force_login(actor)

        with (
            patch("apps.employee.admin.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("admin:employee_employee_change", args=[target.pk]),
                {
                    "username": target.username,
                    "last_name": "Не должно сохраниться",
                    "first_name": "",
                    "email": "",
                    "org": "81000",
                    "date_joined_0": target.date_joined.strftime("%Y-%m-%d"),
                    "date_joined_1": target.date_joined.strftime("%H:%M:%S"),
                    "is_active": "on",
                    "groups": [operator_group.pk],
                    "_save": "Сохранить",
                },
            )

        target.refresh_from_db()
        self.assertEqual(target.last_name, "Исходное")
        self.assertFalse(target.groups.exists())

    def test_bulk_unlock_rolls_back_entire_batch_when_audit_fails(self):
        first = Employee.objects.create_user(
            username="bulk_unlock_first",
            password="GoodPass!1",
            org=81000,
            failed_attempts=5,
        )
        second = Employee.objects.create_user(
            username="bulk_unlock_second",
            password="GoodPass!1",
            org=81000,
            failed_attempts=7,
        )
        request = SimpleNamespace(user=self.user, META={})
        model_admin = admin.site._registry[Employee]

        with (
            patch(
                "apps.employee.admin.log_event",
                side_effect=[None, RuntimeError("audit")],
            ),
            self.assertRaises(RuntimeError),
        ):
            unlock_accounts(
                model_admin,
                request,
                Employee.objects.filter(pk__in=(first.pk, second.pk)).order_by("pk"),
            )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.failed_attempts, 5)
        self.assertEqual(second.failed_attempts, 7)


class GroupProxyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_role_groups()

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

    def test_admin_permission_change_records_subject_audit(self):
        actor = Employee.objects.create_superuser(
            username="role_admin_actor",
            password="GoodPass!1",
            org=81000,
        )
        role = GroupProxy.objects.get(name="ОП1")
        role.permissions.clear()
        permission = Permission.objects.order_by("pk").first()
        self.client.force_login(actor)

        response = self.client.post(
            reverse("admin:employee_groupproxy_change", args=[role.pk]),
            {"permissions": [permission.pk], "_save": "Сохранить"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(role.permissions.filter(pk=permission.pk).exists())
        event = EventLog.objects.get(
            target=f"admin:role:{role.pk}:permissions"
        )
        self.assertEqual(event.event_type, EventLog.EventType.UPDATE)
        self.assertEqual(event.user, actor)

    def test_admin_permission_change_rolls_back_when_audit_fails(self):
        actor = Employee.objects.create_superuser(
            username="role_admin_rollback_actor",
            password="GoodPass!1",
            org=81000,
        )
        role = GroupProxy.objects.get(name="ОП1")
        permissions = list(Permission.objects.order_by("pk")[:2])
        role.permissions.set([permissions[0]])
        self.client.force_login(actor)

        with (
            patch("apps.employee.admin.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("admin:employee_groupproxy_change", args=[role.pk]),
                {"permissions": [permissions[1].pk], "_save": "Сохранить"},
            )

        self.assertEqual(
            set(role.permissions.values_list("pk", flat=True)),
            {permissions[0].pk},
        )
