"""Маршрутизация модуля «Обмен данными» (Этап 3)."""

from django.urls import path

from apps.exchange import views

app_name = "exchange"

urlpatterns = [
    path("upload/", views.exchange_upload, name="upload"),
    path("logs/", views.exchange_logs, name="logs"),
    path("export/", views.exchange_export, name="export"),
    path("export/contract/", views.exchange_export_contract, name="export_contract"),
    path("logs/<int:pk>/", views.exchange_protocol, name="protocol"),
]
