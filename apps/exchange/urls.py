"""Маршрутизация модуля «Обмен данными» (Этап 3)."""

from django.urls import path

from apps.exchange import views

app_name = "exchange"

urlpatterns = [
    path("upload/", views.exchange_upload, name="upload"),
    path("logs/", views.exchange_logs, name="logs"),
    path("logs/<int:pk>/", views.exchange_protocol, name="protocol"),
]
