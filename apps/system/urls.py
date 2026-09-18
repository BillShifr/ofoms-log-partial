"""Маршруты общесистемных модулей (ТЗ разд. 3)."""

from django.urls import path

from apps.system import views

app_name = "system"

urlpatterns = [
    # Пользователи (3.5)
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_update, name="user_update"),
    path("users/<int:pk>/block/", views.user_block, name="user_block"),
    path("users/<int:pk>/unblock/", views.user_unblock, name="user_unblock"),
    path("groups/", views.group_list, name="groups"),
    path("groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
    # Журнал событий (3.4)
    path("events/", views.event_list, name="events"),
    path("events/suggest/", views.event_initiator_suggest, name="event_initiator_suggest"),
    path("events/export/", views.event_export, name="events_export"),
    # Сообщения (3.3, PRD v3 §2.6)
    path("messages/", views.message_list, name="messages"),
    path("messages/users/suggest/", views.users_suggest, name="users_suggest"),
    path("messages/new/", views.conversation_create, name="conversation_create"),
    path("messages/conversation/<int:pk>/", views.conversation_detail, name="conversation"),
    path("messages/conversation/<int:pk>/threads/new/", views.conversation_thread_create, name="thread_create"),
    path("messages/thread/<int:pk>/", views.thread_detail, name="thread"),
    path("messages/thread/<int:pk>/toggle/", views.thread_toggle, name="thread_toggle"),
    path("messages/thread/<int:pk>/reply/", views.thread_reply, name="reply"),
    path("messages/thread/<int:pk>/react/", views.thread_react, name="react"),
    path("messages/attachments/<int:pk>/download/", views.message_attachment_download, name="message_attachment_download"),
    # Задачи (3.6)
    path("tasks/", views.task_list, name="tasks"),
    path("tasks/assignees/suggest/", views.task_assignee_suggest, name="task_assignee_suggest"),
    path("tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:pk>/", views.task_update, name="task_update"),
    path("tasks/<int:pk>/run/", views.task_run, name="task_run"),
    path("tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),
    path("tasks/files/<int:pk>/download/", views.task_file_download, name="task_file_download"),
    # Документация (3.7)
    path("docs/", views.doc_list, name="docs"),
    path("docs/suggest/", views.doc_suggest, name="doc_suggest"),
    path("docs/upload/", views.doc_upload, name="doc_upload"),
    path("docs/<int:pk>/view/", views.doc_view, name="doc_view"),
    path("docs/<int:pk>/download/", views.doc_download, name="doc_download"),
    path("docs/<int:pk>/delete/", views.doc_delete, name="doc_delete"),
    path("docs/category/<slug:slug>/", views.doc_category, name="doc_category"),
    # Новости (3.8, PRD v3 §2.7)
    path("news/", views.news_list, name="news"),
    path("news/suggest/", views.news_suggest, name="news_suggest"),
    path("news/new/", views.news_create, name="news_create"),
    path("news/<int:pk>/", views.news_detail, name="news_detail"),
    path("news/<int:pk>/cover/", views.news_cover, name="news_cover"),
    path("news/<int:pk>/edit/", views.news_update, name="news_update"),
    path("news/<int:pk>/toggle/", views.news_toggle, name="news_toggle"),
    path("news/<int:pk>/delete/", views.news_delete, name="news_delete"),
    # Настройка пользовательского интерфейса (3.2)
    path("prefs/", views.prefs_list, name="prefs"),
    path("prefs/<str:table_key>/", views.table_prefs, name="table_prefs"),
]
