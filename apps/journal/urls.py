"""Маршрутизация кастомного экрана журнала (Этапы 2, 4).

- /journal/            — реестр обращений (таблица + фильтры);
- /journal/new/        — ручная регистрация;
- /journal/<pk>/       — полная карточка (РКК);
- /journal/<pk>/edit/  — редактирование;
- /journal/<pk>/print/ — печатная форма (п. 35);
- /journal/<pk>/answer/ — добавление ответа (п. 215);
- /journal/<pk>/file/  — прикрепление файла (п. 200);
- /journal/<pk>/redirect/ — переадресация (п. 212);
- /journal/<pk>/cover/ — сопроводительное письмо (п. 212).
"""

from django.urls import path

from apps.journal import views

app_name = "journal"

urlpatterns = [
    path("", views.irp_list, name="list"),
    path("print/", views.irp_list_print, name="list_print"),
    path("suggest/", views.irp_suggest, name="suggest"),
    path("new/", views.irp_create, name="create"),
    path("themes/new/", views.irp_theme_create, name="theme_create"),
    path("<int:pk>/", views.irp_detail, name="detail"),
    path("<int:pk>/edit/", views.irp_edit, name="edit"),
    path("<int:pk>/print/", views.irp_print, name="print"),
    path("<int:pk>/answer/", views.irp_answer_create, name="answer"),
    path("<int:pk>/file/", views.irp_file_upload, name="file"),
    path("files/<int:pk>/download/", views.irp_file_download, name="file_download"),
    path("<int:pk>/redirect/", views.irp_redirect, name="redirect"),
    path("<int:pk>/cover/", views.irp_cover, name="cover"),
]
