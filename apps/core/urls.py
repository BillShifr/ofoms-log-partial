"""Маршруты общесистемных функций."""

from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("token-login/", views.token_login, name="token_login"),
]
