"""Тесты employee: модель Employee и GroupProxy."""

from apps.employee.models import Employee, GroupProxy
from django.contrib.auth import authenticate, get_user_model
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


class GroupProxyTests(TestCase):
    def test_proxy_model(self):
        GroupProxy.objects.get_or_create(name="Тестовая роль")
        self.assertTrue(GroupProxy.objects.filter(name="Тестовая роль").exists())
