"""Администрирование общесистемных модулей."""

from django.contrib import admin

from apps.core.admin_utils import (
    AuditedAdminMixin,
    ParticipantScopedAdminMixin,
    ReadOnlyAdminMixin,
)
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
class NewsCategoryAdmin(AuditedAdminMixin, admin.ModelAdmin):
    audit_module = "system"
    list_display = ("name", "slug", "icon")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(NewsItem)
class NewsItemAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "category", "author", "is_active", "is_pinned", "views_count", "created_at")
    list_filter = ("is_active", "is_pinned", "category")
    search_fields = ("title", "summary", "text")


@admin.register(SystemDocument)
class SystemDocumentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "sort_order", "uploaded_by", "created_at")
    search_fields = ("title", "description")


@admin.register(Conversation)
class ConversationAdmin(
    ParticipantScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    list_display = ("id", "title", "created_at", "updated_at")


@admin.register(MessageThread)
class MessageThreadAdmin(
    ParticipantScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    participant_lookup = "conversation__participants"
    list_display = ("id", "conversation", "title", "created_by", "is_closed", "created_at")
    list_filter = ("is_closed",)


@admin.register(MessageReply)
class MessageReplyAdmin(
    ParticipantScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    participant_lookup = "thread__conversation__participants"
    list_display = ("id", "thread", "author", "created_at", "edited_at")
    search_fields = ("body",)


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(
    ParticipantScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    participant_lookup = "reply__thread__conversation__participants"
    list_display = ("id", "reply", "uploaded_by", "created_at")
    search_fields = ("file",)


@admin.register(TaskJob)
class TaskJobAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "command", "run_mode", "enabled", "last_result", "last_finished_at")
    list_filter = ("enabled", "run_mode", "command")


@admin.register(TaskRun)
class TaskRunAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("task", "triggered_by", "queued_at", "started_at", "attempt", "result")
    list_filter = ("triggered_by", "result")


@admin.register(UserTableViewPref)
class UserTableViewPrefAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("user", "table_key", "updated_at")
    list_filter = ("table_key",)
