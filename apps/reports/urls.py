"""Маршрутизация модуля отчётов (Этап 5)."""

from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.reports_index, name="index"),
    path("<slug:slug>/", views.report_detail, name="detail"),
    path("<slug:slug>/export/<str:fmt>/", views.report_export, name="export"),
]
