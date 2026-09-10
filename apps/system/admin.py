"""Администрирование общесистемных модулей."""

from django.contrib import admin

from apps.system.models import (
    Conversation,
    MessageAttachment,
    MessageReply,
    MessageThread,
    NewsCategory,
    NewsItem,
    SystemDocument,
    TaskJob,
    TaskRun,
    UserTableViewPref,
)


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "icon")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(NewsItem)
class NewsItemAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "author", "is_active", "is_pinned", "views_count", "created_at")
    list_filter = ("is_active", "is_pinned", "category")
    search_fields = ("title", "summary", "text")


@admin.register(SystemDocument)
class SystemDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "sort_order", "uploaded_by", "created_at")
    search_fields = ("title", "description")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "created_at", "updated_at")


@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "title", "created_by", "is_closed", "created_at")
    list_filter = ("is_closed",)


@admin.register(MessageReply)
class MessageReplyAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "author", "created_at", "edited_at")
    search_fields = ("body",)


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "reply", "uploaded_by", "created_at")
    search_fields = ("file",)


@admin.register(TaskJob)
class TaskJobAdmin(admin.ModelAdmin):
    list_display = ("name", "command", "run_mode", "enabled", "last_result", "last_finished_at")
    list_filter = ("enabled", "run_mode", "command")


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ("task", "triggered_by", "started_at", "result")
    list_filter = ("triggered_by", "result")


@admin.register(UserTableViewPref)
class UserTableViewPrefAdmin(admin.ModelAdmin):
    list_display = ("user", "table_key", "updated_at")
    list_filter = ("table_key",)
