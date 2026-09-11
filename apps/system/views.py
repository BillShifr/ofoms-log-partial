"""Вьюхи общесистемных модулей.

Доступы:
- всем аутентифицированным: Сообщения, Новости, Документация, Настройки таблиц;
- роли «Администратор»/суперпользователю: Пользователи, Журнал событий, Задачи,
  управление Новостями/Документацией (ТЗ разд. 3, п. «доступ при наличии прав»).
"""

import mimetypes
from functools import wraps
from pathlib import PurePosixPath

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import CharField, Count, F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Concat
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.fold import contains_folded, filter_contains_any
from apps.core.models import EventLog, log_event
from apps.core.policy import role_codes_for_user
from apps.core.roles import Roles
from apps.core.storage import open_field_file_or_404
from apps.employee.models import Employee
from apps.journal.table import JOURNAL_COLUMNS, JOURNAL_TABLE_KEY, SORTABLE_FIELDS
from apps.system.forms import (
    DocForm,
    EmployeeCreateForm,
    EmployeeFilterForm,
    EmployeeUpdateForm,
    EventFilterForm,
    NewConversationForm,
    NewsForm,
    ReplyForm,
    TaskFileForm,
    TaskForm,
    TaskNoteForm,
    TaskReportForm,
    ThreadForm,
)
from apps.system.models import (
    Conversation,
    DocCategory,
    MessageAttachment,
    MessageReply,
    MessageThread,
    NewsCategory,
    NewsItem,
    SystemDocument,
    TaskAlreadyRunning,
    TaskFile,
    TaskJob,
    TaskNote,
    UserTableViewPref,
)
from apps.system.validators import VIDEO_EXTENSIONS

PAGE_SIZE = 25


def _is_admin(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or Roles.ADMIN in role_codes_for_user(user))
    )


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _is_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _paginate(request, qs, per_page=PAGE_SIZE):
    paginator = Paginator(qs, per_page)
    try:
        return paginator.page(int(request.GET.get("page", 1)))
    except Exception:  # noqa: BLE001 — невалидный номер страницы -> последняя
        return paginator.page(paginator.num_pages or 1)


# ---------------------------------------------------------------------------
# Пользователи (ТЗ разд. 3.5)
# ---------------------------------------------------------------------------


@admin_required
def user_list(request):
    form = EmployeeFilterForm(request.GET or None)
    qs = Employee.objects.prefetch_related("groups").order_by("last_name", "first_name")
    if form.is_valid():
        cd = form.cleaned_data
        if cd["q"]:
            qs = models_q_lookup(qs, cd["q"])
        if cd["org"]:
            qs = qs.filter(org=cd["org"])
        if cd["locked"]:
            qs = qs.filter(lock_until__gt=timezone.now())

    page = _paginate(request, qs)
    return render(
        request,
        "system/users.html",
        {
            "page": page,
            "form": form,
            "active_nav": "users",
        },
    )


def models_q_lookup(qs, q):
    from apps.core.fold import filter_contains_any

    fields = ("last_name", "first_name", "username", "job_title")
    for i, word in enumerate(q.strip().split()):
        qs = filter_contains_any(qs, fields, word, prefix=f"qfold_{i}")
    return qs


@admin_required
@require_http_methods(["GET", "POST"])
def user_create(request):
    if request.method == "POST":
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_event(
                module="employee",
                event_type=EventLog.EventType.CREATE,
                user=request.user,
                target=f"employee:{user.pk}:{user.username}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, f"Учётная запись «{user.username}» создана.")
            return redirect("system:users")
    else:
        form = EmployeeCreateForm()
    return render(
        request,
        "system/user_form.html",
        _user_form_context(form, "Новый пользователь"),
    )


@admin_required
@require_http_methods(["GET", "POST"])
def user_update(request, pk):
    user = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        form = EmployeeUpdateForm(request.POST, instance=user, actor=request.user)
        if form.is_valid():
            changed = list(form.changed_data)
            form.save()
            log_event(
                module="employee",
                event_type=EventLog.EventType.UPDATE,
                user=request.user,
                target=f"employee:{user.pk}:{user.username}:{','.join(changed)}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Учётная запись обновлена.")
            return redirect("system:users")
    else:
        form = EmployeeUpdateForm(instance=user, actor=request.user)
    return render(
        request,
        "system/user_form.html",
        _user_form_context(form, f"Пользователь: {user.username}", user=user),
    )


def _user_form_context(form, title, *, user=None):
    from apps.core.policy import CAPABILITY_LABELS, capability_matrix

    return {
        "form": form,
        "user": user,
        "title": title,
        "capability_headers": CAPABILITY_LABELS.values(),
        "capability_matrix": capability_matrix(),
        "active_nav": "users",
    }


@admin_required
@require_http_methods(["POST"])
def user_block(request, pk):
    user = get_object_or_404(Employee, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "Нельзя заблокировать собственную учётную запись.")
        return redirect("system:users")
    user.is_active = False
    user.save(update_fields=["is_active"])
    log_event(
        module="employee",
        event_type=EventLog.EventType.BLOCK,
        user=request.user,
        target=f"employee:{user.pk}:{user.username}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"Учётная запись «{user.username}» заблокирована.")
    return redirect("system:users")


@admin_required
@require_http_methods(["POST"])
def user_unblock(request, pk):
    user = get_object_or_404(Employee, pk=pk)
    user.is_active = True
    user.reset_failed_logins()
    user.save(update_fields=["is_active"])
    log_event(
        module="employee",
        event_type=EventLog.EventType.UNBLOCK,
        user=request.user,
        target=f"employee:{user.pk}:{user.username}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"Учётная запись «{user.username}» разблокирована.")
    return redirect("system:users")


# ---------------------------------------------------------------------------
# Журнал событий (ТЗ разд. 3.4)
# ---------------------------------------------------------------------------


def _events_qs(form):
    qs = EventLog.objects.select_related("user")
    if form.is_valid():
        cd = form.cleaned_data
        if cd["module"]:
            qs = qs.filter(module=cd["module"])
        if cd["event_type"]:
            qs = qs.filter(event_type=cd["event_type"])
        if cd["result"]:
            qs = qs.filter(result=cd["result"])
        if cd["user"]:
            qs = qs.filter(user=cd["user"])
        if cd["target"]:
            qs = contains_folded(qs, "target", cd["target"])
        if cd["date_from"]:
            qs = qs.filter(started_at__gte=cd["date_from"])
        if cd["date_to"]:
            qs = qs.filter(started_at__lte=cd["date_to"])
    return qs


@admin_required
@require_http_methods(["GET"])
def event_initiator_suggest(request):
    """Автозаполнение инициатора события (PRD v3 §2.10, §2.0.6)."""
    from django.http import JsonResponse

    q = (request.GET.get("q") or "").strip()
    if len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = Employee.objects.annotate(
        search_name=Concat(
            Coalesce("last_name", Value("")),
            Value(" "),
            Coalesce("first_name", Value("")),
            output_field=CharField(),
        )
    )
    qs = filter_contains_any(
        qs, ("search_name", "username"), q, prefix="event_initiator_search_"
    )
    rows = qs.order_by("last_name", "first_name", "pk").values(
        "id", "last_name", "first_name", "username"
    )[:10]
    matches = []
    for e in rows:
        text = f"{e.get('last_name') or ''} {e.get('first_name') or ''}".strip() or e.get("username") or ""
        matches.append({"id": e["id"], "label": text})
    return JsonResponse({"suggestions": matches})


@admin_required
def event_list(request):
    from django.urls import reverse

    form = EventFilterForm(request.GET or None)
    qs = _events_qs(form)

    initiator_label = None
    if form.is_valid() and form.cleaned_data.get("user"):
        u = form.cleaned_data["user"]
        initiator_label = f"{u.last_name} {u.first_name}".strip() or u.username

    page = _paginate(request, qs)
    return render(
        request,
        "system/events.html",
        {
            "page": page,
            "form": form,
            "active_nav": "events",
            "initiator_label": initiator_label,
            "suggest_url": reverse("system:event_initiator_suggest"),
        },
    )


@admin_required
@require_http_methods(["GET"])
def event_export(request):
    """Выгрузка журнала событий в Excel (ТЗ разд. 3.4/2.10)."""
    form = EventFilterForm(request.GET)
    if not form.is_valid():
        return HttpResponse(status=400)
    rows = _events_qs(form)[:5000]

    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    from apps.core.exports import excel_safe_value

    wb = Workbook()
    ws = wb.active
    ws.title = "События"
    header = ["ID", "Начало", "Завершение", "Тип", "Модуль", "Результат",
              "Инициатор", "Объект", "IP", "Длительность, мс"]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
    for e in rows:
        ws.append([excel_safe_value(value) for value in [
            e.id,
            e.started_at.strftime("%d.%m.%Y %H:%M:%S") if e.started_at else "",
            e.finished_at.strftime("%d.%m.%Y %H:%M:%S") if e.finished_at else "",
            e.get_event_type_display(),
            e.module,
            e.get_result_display(),
            str(e.user) if e.user else "",
            e.target,
            e.ip,
            e.duration_ms or "",
        ]])
    for col, width in zip(("ABCDEFGHIJ"), (8, 20, 20, 18, 12, 12, 28, 30, 16, 12), strict=True):
        ws.column_dimensions[col].width = width

    buf = BytesIO()
    wb.save(buf)
    log_event(
        module="system",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target="events:export",
        ip=request.META.get("REMOTE_ADDR"),
    )
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="events.xlsx"'
    return response


# ---------------------------------------------------------------------------
# Сообщения: внутренний мессенджер (ТЗ разд. 3.3, PRD v3 §2.6)
# ---------------------------------------------------------------------------

EMOJI_SET = ("👍", "👎", "❤️", "😊", "❗")


def _conversation_unread_counts(user) -> dict:
    """Словарь {conversation_id: число непрочитанных сообщений}."""
    rows = (
        MessageReply.objects.filter(thread__conversation__participants=user)
        .exclude(author=user)
        .exclude(read_by=user)
        .values("thread__conversation_id")
        .annotate(total=Count("id"))
    )
    return {row["thread__conversation_id"]: row["total"] for row in rows}


def _thread_unread_counts(user, conversation) -> dict:
    rows = (
        MessageReply.objects.filter(thread__conversation=conversation)
        .exclude(author=user)
        .exclude(read_by=user)
        .values("thread_id")
        .annotate(total=Count("id"))
    )
    return {row["thread_id"]: row["total"] for row in rows}


def _mark_read_for_user(user, thread_qs):
    """Атомарно помечает все сообщения выбранных тем прочитанными."""
    reply_ids = list(
        MessageReply.objects.filter(thread__in=thread_qs)
        .exclude(author=user)
        .exclude(read_by=user)
        .values_list("id", flat=True)
    )
    relation = MessageReply._meta.get_field("read_by")
    through = relation.remote_field.through
    reply_key = f"{relation.m2m_field_name()}_id"
    user_key = f"{relation.m2m_reverse_field_name()}_id"
    through.objects.bulk_create(
        [through(**{reply_key: reply_id, user_key: user.pk}) for reply_id in reply_ids],
        ignore_conflicts=True,
        batch_size=500,
    )


def _participant_or_404(user, conversation):
    if not conversation.participants.filter(pk=user.pk).exists():
        raise PermissionDenied
    return conversation


def _conversations_meta(user, q=""):
    """Список диалогов пользователя с последним сообщением и счётчиком
    непрочитанных; при q — фильтр по теме, участникам и тексту."""
    unread_counts = _conversation_unread_counts(user)
    latest_reply = MessageReply.objects.filter(
        thread__conversation=OuterRef("pk")
    ).order_by("-created_at", "-pk")
    conversations = Conversation.objects.filter(participants=user).annotate(
        latest_reply_id=Subquery(latest_reply.values("pk")[:1])
    )
    if q:
        conversations = conversations.annotate(
            participant_name=Concat(
                Coalesce("participants__first_name", Value("")),
                Value(" "),
                Coalesce("participants__last_name", Value("")),
                output_field=CharField(),
            )
        )
        conversations = filter_contains_any(
            conversations,
            ("title", "participant_name", "participants__username", "threads__replies__body"),
            q,
            prefix="conversation_search_",
        ).distinct()
    conversations = list(conversations.prefetch_related("participants"))
    latest_by_id = MessageReply.objects.select_related("author").in_bulk(
        conv.latest_reply_id for conv in conversations if conv.latest_reply_id
    )
    meta = []
    for conv in conversations:
        last = latest_by_id.get(conv.latest_reply_id)
        meta.append(
            {
                "conv": conv,
                "last": last,
                "unread": unread_counts.get(conv.pk, 0),
            }
        )
    meta.sort(
        key=lambda m: (m["last"].created_at if m["last"] else m["conv"].created_at),
        reverse=True,
    )
    return meta


@login_required
def message_list(request):
    """Список диалогов (левая панель) + форма создания диалога."""
    q = (request.GET.get("q") or "").strip().lower()
    meta = _conversations_meta(request.user, q)
    return render(
        request,
        "system/messages.html",
        {
            "conversations": meta,
            "unread_total": sum(m["unread"] for m in meta),
            "form": NewConversationForm(),
            "q": q,
            "active_nav": "messages",
            "emoji_set": EMOJI_SET,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def conversation_create(request):
    """Создание диалога (сворачиваемая форма на странице сообщений)."""
    if request.method == "GET":
        return redirect("system:messages")
    form = NewConversationForm(request.POST)
    if form.is_valid():
        conv = form.save(commit=False)
        conv.save()
        conv.participants.set(list(form.cleaned_data["participants"]) + [request.user])
        log_event(
            module="system",
            event_type=EventLog.EventType.CREATE,
            user=request.user,
            target=f"conversation:{conv.pk}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Диалог создан.")
        return redirect("system:conversation", conv.pk)
    messages.error(request, "Не удалось создать диалог: проверьте форму.")
    return redirect("system:messages")


@login_required
def conversation_detail(request, pk):
    """Диалог: список тем/веток + создание новой темы."""
    conv = get_object_or_404(
        Conversation.objects.prefetch_related("participants"), pk=pk
    )
    _participant_or_404(request.user, conv)
    threads = list(
        MessageThread.objects.filter(conversation=conv).select_related("created_by")
    )
    unread_counts = _thread_unread_counts(request.user, conv)
    for thread in threads:
        thread.unread_count = unread_counts.get(thread.pk, 0)
    return render(
        request,
        "system/conversation.html",
        {
            "conv": conv,
            "threads": threads,
            "thread_form": ThreadForm(),
            "conversations": _conversations_meta(request.user),
            "unread_total": sum(unread_counts.values()),
            "active_nav": "messages",
            "emoji_set": EMOJI_SET,
        },
    )


@login_required
@require_http_methods(["POST"])
def conversation_thread_create(request, pk):
    """Новая тема внутри диалога."""
    conv = _participant_or_404(request.user, get_object_or_404(Conversation, pk=pk))
    form = ThreadForm(request.POST)
    if form.is_valid():
        thread = form.save(commit=False)
        thread.conversation = conv
        thread.created_by = request.user
        thread.save()
        log_event(
            module="system",
            event_type=EventLog.EventType.CREATE,
            user=request.user,
            target=f"thread:{thread.pk}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        return redirect("system:thread", thread.pk)
    messages.error(request, "Не удалось создать тему: укажите тему обсуждения.")
    return redirect("system:conversation", conv.pk)


@login_required
def thread_detail(request, pk):
    """Тема: лента сообщений, ответы, реакции, вложения."""
    thread = get_object_or_404(
        MessageThread.objects.select_related("conversation", "created_by"), pk=pk
    )
    conv = _participant_or_404(request.user, thread.conversation)
    _mark_read_for_user(request.user, MessageThread.objects.filter(pk=thread.pk))
    replies = (
        thread.replies.select_related("author")
        .prefetch_related("attachments")
        .order_by("created_at")
    )
    thread_replies = list(replies)
    return render(
        request,
        "system/message_thread.html",
        {
            "conv": conv,
            "thread": thread,
            "replies": thread_replies,
            "reply_form": ReplyForm(),
            "conversations": _conversations_meta(request.user),
            "emoji_set": EMOJI_SET,
            "active_nav": "messages",
        },
    )


@login_required
@require_http_methods(["POST"])
def thread_reply(request, pk):
    """Ответ в теме (с необязательным вложением-файлом)."""
    thread = get_object_or_404(MessageThread, pk=pk)
    _participant_or_404(request.user, thread.conversation)
    if thread.is_closed:
        raise PermissionDenied
    form = ReplyForm(request.POST)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.thread = thread
        reply.author = request.user
        parent_id = (request.POST.get("parent") or "").strip()
        if parent_id and parent_id.isdigit():
            parent = MessageReply.objects.filter(pk=parent_id, thread=thread).first()
            reply.parent = parent
        reply.save()
        uploaded = request.FILES.get("attachment")
        if uploaded is not None:
            from apps.system.validators import validate_attachment_file

            try:
                validate_attachment_file(uploaded)
            except Exception:  # noqa: BLE001 — не прошедший валидацию файл
                messages.error(request, "Вложение не прикреплено: недопустимый тип или размер файла.")
            else:
                MessageAttachment.objects.create(
                    reply=reply, file=uploaded, uploaded_by=request.user
                )
        log_event(
            module="system",
            event_type=EventLog.EventType.SEND,
            user=request.user,
            target=f"thread:{thread.pk}:reply:{reply.pk}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Сообщение отправлено.")
    else:
        messages.error(request, "Не удалось отправить сообщение: проверьте форму.")
    return redirect("system:thread", thread.pk)


@login_required
@require_http_methods(["GET"])
def message_attachment_download(request, pk):
    """Выдаёт вложение только участнику родительского диалога."""
    attachment = get_object_or_404(
        MessageAttachment.objects.select_related("reply__thread__conversation"),
        pk=pk,
    )
    _participant_or_404(request.user, attachment.reply.thread.conversation)
    file_handle = open_field_file_or_404(attachment.file)
    log_event(
        module="system",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target=f"message-attachment:{attachment.pk}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    return FileResponse(
        file_handle,
        filename=attachment.file.name.rsplit("/", 1)[-1],
        as_attachment=True,
    )


@login_required
@require_http_methods(["POST"])
def thread_react(request, pk):
    """Переключение реакции пользователя на сообщение."""
    reply = get_object_or_404(
        MessageReply.objects.select_related("thread__conversation"), pk=pk
    )
    _participant_or_404(request.user, reply.thread.conversation)
    emoji = request.POST.get("emoji", "")
    if emoji not in EMOJI_SET:
        return redirect("system:thread", reply.thread_id)
    reactions = dict(reply.reactions or {})
    users = list(reactions.get(emoji, []))
    if request.user.pk in users:
        users.remove(request.user.pk)
        if not users:
            reactions.pop(emoji, None)
        else:
            reactions[emoji] = users
    else:
        users.append(request.user.pk)
        reactions[emoji] = users
    reply.reactions = reactions
    reply.save(update_fields=["reactions"])
    return redirect("system:thread", reply.thread_id)


@login_required
@require_http_methods(["GET"])
def users_suggest(request):
    """Автозаполнение имён участников диалога (PRD v3 §2.0.6)."""
    from django.http import JsonResponse

    q = (request.GET.get("q") or "").strip()
    if len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = Employee.objects.filter(is_active=True).annotate(
        search_name=Concat(
            Coalesce("first_name", Value("")),
            Value(" "),
            Coalesce("last_name", Value("")),
            output_field=CharField(),
        )
    )
    qs = filter_contains_any(
        qs, ("search_name", "username"), q, prefix="participant_search_"
    )
    employees = qs.order_by("last_name", "first_name", "pk")[:8]
    suggestions = [
        {
            "id": employee.pk,
            "label": f"{employee.full_name() or employee.username} ({employee.get_org_display()})",
        }
        for employee in employees
    ]
    return JsonResponse({"suggestions": suggestions})


# ---------------------------------------------------------------------------
# Задачи (ТЗ разд. 3.6)
# ---------------------------------------------------------------------------


@admin_required
def task_list(request):
    tasks = TaskJob.objects.select_related("assigned_to", "created_by").prefetch_related("runs")
    from apps.system.tasks import TASK_COMMAND_LABELS

    return render(
        request,
        "system/tasks.html",
        {"tasks": tasks, "command_tips": TASK_COMMAND_LABELS, "active_nav": "tasks"},
    )


@admin_required
@require_http_methods(["GET"])
def task_assignee_suggest(request):
    """Автозаполнение исполнителя задачи из справочника сотрудников (PRD v3 §2.0.6, §2.11)."""
    from django.http import JsonResponse

    q = (request.GET.get("q") or "").strip()
    if len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = Employee.objects.filter(is_active=True).annotate(
        search_name=Concat(
            Coalesce("last_name", Value("")),
            Value(" "),
            Coalesce("first_name", Value("")),
            output_field=CharField(),
        )
    )
    qs = filter_contains_any(
        qs, ("search_name", "username"), q, prefix="assignee_search_"
    )
    rows = qs.order_by("last_name", "first_name", "pk").values(
        "id", "last_name", "first_name", "username"
    )[:10]
    matches = []
    for employee in rows:
        label = (
            f"{employee['last_name']} {employee['first_name']}".strip()
            or employee["username"]
        )
        matches.append({"id": employee["id"], "label": label})
    return JsonResponse({"suggestions": matches})


@admin_required
@require_http_methods(["GET", "POST"])
def task_create(request):
    if request.method == "POST":
        form = TaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.save()
            log_event(
                module="system",
                event_type=EventLog.EventType.CREATE,
                user=request.user,
                target=f"task:{task.pk}:{task.command}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Задание создано.")
            return redirect("system:tasks")
    else:
        form = TaskForm()
    return render(request, "system/task_form.html", {"form": form, "title": "Новое задание", "active_nav": "tasks"})


@admin_required
@require_http_methods(["GET", "POST"])
def task_update(request, pk):
    task = get_object_or_404(
        TaskJob.objects.select_related("assigned_to", "created_by"), pk=pk
    )
    from apps.system.tasks import TASK_COMMAND_LABELS

    action = request.POST.get("action") if request.method == "POST" else None
    if action == "note":
        note_form = TaskNoteForm(request.POST)
        if note_form.is_valid():
            note = note_form.save(commit=False)
            note.task = task
            note.author = request.user
            note.save()
            log_event(module="system", event_type=EventLog.EventType.UPDATE,
                      user=request.user, target=f"task:{task.pk}:note",
                      ip=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Заметка добавлена.")
        return redirect("system:task_update", pk=task.pk)
    if action == "note_edit":
        try:
            note = task.notes.get(pk=request.POST.get("note_id"))
        except TaskNote.DoesNotExist:
            messages.error(request, "Заметка не найдена.")
        else:
            text = (request.POST.get("text") or "").strip()
            if text:
                note.text = text
                note.save()
                log_event(module="system", event_type=EventLog.EventType.UPDATE,
                          user=request.user, target=f"task:{task.pk}:note:{note.pk}",
                          ip=request.META.get("REMOTE_ADDR"))
                messages.success(request, "Заметка обновлена.")
            else:
                messages.error(request, "Текст заметки пуст.")
        return redirect("system:task_update", pk=task.pk)
    if action == "note_delete":
        try:
            note = task.notes.get(pk=request.POST.get("note_id"))
        except TaskNote.DoesNotExist:
            messages.error(request, "Заметка не найдена.")
        else:
            note.delete()
            log_event(module="system", event_type=EventLog.EventType.DELETE,
                      user=request.user, target=f"task:{task.pk}:note:{note.pk}",
                      ip=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Заметка удалена.")
        return redirect("system:task_update", pk=task.pk)
    if action == "file":
        file_form = TaskFileForm(request.POST, request.FILES)
        if file_form.is_valid():
            tf = file_form.save(commit=False)
            tf.task = task
            tf.uploaded_by = request.user
            tf.save()
            log_event(module="system", event_type=EventLog.EventType.UPDATE,
                      user=request.user, target=f"task:{task.pk}:file",
                      ip=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Файл прикреплён.")
        else:
            messages.error(
                request,
                "Файл не прикреплён: допустимы документы и архивы до 20 МБ.",
            )
        return redirect("system:task_update", pk=task.pk)
    if action == "report":
        report_form = TaskReportForm(request.POST)
        if report_form.is_valid():
            rep = report_form.save(commit=False)
            rep.task = task
            rep.save()
            log_event(module="system", event_type=EventLog.EventType.UPDATE,
                      user=request.user, target=f"task:{task.pk}:report",
                      ip=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Отчёт сохранён.")
        return redirect("system:task_update", pk=task.pk)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            log_event(
                module="system",
                event_type=EventLog.EventType.UPDATE,
                user=request.user,
                target=f"task:{task.pk}:{task.command}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Задание обновлено.")
            return redirect("system:task_update", pk=task.pk)
    else:
        form = TaskForm(instance=task)

    return render(
        request,
        "system/task_form.html",
        {
            "form": form,
            "task": task,
            "title": f"Задание: {task.name}",
            "runs": task.runs.all(),
            "notes": task.notes.all(),
            "files": task.files.all(),
            "reports": task.reports.all(),
            "note_form": TaskNoteForm(),
            "file_form": TaskFileForm(),
            "report_form": TaskReportForm(),
            "command_tips": TASK_COMMAND_LABELS,
            "active_nav": "tasks",
        },
    )


@admin_required
@require_http_methods(["POST"])
def task_run(request, pk):
    task = get_object_or_404(TaskJob, pk=pk)
    try:
        run = task.run(user=request.user)
    except TaskAlreadyRunning:
        messages.warning(request, f"Задание «{task.name}» уже выполняется.")
        return redirect("system:task_update", pk=task.pk)
    if run.result == EventLog.Result.OK:
        messages.success(request, f"Задание «{task.name}» выполнено успешно.")
    else:
        messages.error(request, f"Задание «{task.name}» завершилось с ошибкой.")
    return redirect("system:task_update", pk=task.pk)


@admin_required
@require_http_methods(["POST"])
def task_toggle(request, pk):
    task = get_object_or_404(TaskJob, pk=pk)
    task.enabled = not task.enabled
    task.save(update_fields=["enabled"])
    state = "включено" if task.enabled else "выключено"
    messages.success(request, f"Задание «{task.name}» {state}.")
    return redirect("system:tasks")


@admin_required
@require_http_methods(["GET"])
def task_file_download(request, pk):
    """Выдаёт служебное вложение задачи только администратору."""
    attachment = get_object_or_404(TaskFile, pk=pk)
    file_handle = open_field_file_or_404(attachment.file)
    log_event(
        module="system",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target=f"task-file:{attachment.pk}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    return FileResponse(
        file_handle,
        filename=attachment.file.name.rsplit("/", 1)[-1],
        as_attachment=True,
    )


# ---------------------------------------------------------------------------
# Документация (ТЗ разд. 3.7)
# ---------------------------------------------------------------------------


@login_required
def doc_list(request):
    """Главная документации (wiki-стиль): карточки категорий + без категории."""
    categories = DocCategory.objects.annotate(docs_total=Count("docs"))
    q = (request.GET.get("q") or "").strip()
    if q:
        docs = filter_contains_any(
            SystemDocument.objects.select_related("category"),
            ("title", "description"),
            q,
            prefix="doc_search_",
        )
    else:
        docs = SystemDocument.objects.filter(category__isnull=True)
    return render(
        request,
        "system/docs.html",
        {
            "categories": categories,
            "category": None,
            "docs": docs,
            "can_manage": _is_admin(request.user),
            "form": DocForm(),
            "active_nav": "docs",
        },
    )


@login_required
def doc_category(request, slug):
    """Документы конкретной категории (wiki-просмотр)."""
    category = get_object_or_404(
        DocCategory.objects.prefetch_related("docs"), slug=slug
    )
    categories = DocCategory.objects.annotate(docs_total=Count("docs"))
    return render(
        request,
        "system/docs.html",
        {
            "categories": categories,
            "category": category,
            "docs": category.docs.all(),
            "can_manage": _is_admin(request.user),
            "form": DocForm(),
            "active_nav": "docs",
        },
    )


@admin_required
@require_http_methods(["POST"])
def doc_upload(request):
    form = DocForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.uploaded_by = request.user
        uploaded = request.FILES.get("file")
        if uploaded:
            doc.file_size = uploaded.size
            name = (uploaded.name or "").lower()
            ext = name.rsplit(".", 1)[-1] if "." in name else ""
            doc.file_type = ext if len(ext) <= 16 else ""
            if not form.cleaned_data.get("title"):
                doc.title = (uploaded.name or "").rsplit(".", 1)[0][:200]
        doc.save()
        log_event(
            module="system",
            event_type=EventLog.EventType.CREATE,
            user=request.user,
            target=f"doc:{doc.pk}:{doc.file.name}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Документ добавлен.")
    else:
        errors = [
            f"{form[field].label}: {e}" for field, errs in form.errors.items() for e in errs
        ]
        detail = "; ".join(errors)
        messages.error(request, f"Не удалось добавить документ. {detail}")
    return redirect("system:docs")


@login_required
@require_http_methods(["GET"])
def doc_download(request, pk):
    """Скачивание документа с учётом счётчика загрузок (PRD v3 §2.8)."""
    doc = get_object_or_404(SystemDocument, pk=pk)
    file_handle = open_field_file_or_404(doc.file)
    SystemDocument.objects.filter(pk=pk).update(downloads_count=F("downloads_count") + 1)
    log_event(
        module="system",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target=f"doc:{doc.pk}:{doc.title}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    return FileResponse(file_handle, filename=doc.file.name.split("/")[-1], as_attachment=True)


@login_required
@require_http_methods(["GET"])
def doc_view(request, pk):
    """Отдаёт видео авторизованному пользователю без публикации MEDIA_ROOT."""
    doc = get_object_or_404(SystemDocument, pk=pk)
    extension = PurePosixPath(doc.file.name).suffix.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise Http404

    filename = doc.file.name.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_handle = open_field_file_or_404(doc.file)
    log_event(
        module="system",
        event_type=EventLog.EventType.VIEW,
        user=request.user,
        target=f"doc:{doc.pk}:view",
        ip=request.META.get("REMOTE_ADDR"),
    )
    return FileResponse(
        file_handle,
        as_attachment=False,
        filename=filename,
        content_type=content_type,
    )


@login_required
@require_http_methods(["GET"])
def doc_suggest(request):
    """Автозаполнение поиска по документам (PRD v3 §2.0.6)."""
    from django.http import JsonResponse

    q = (request.GET.get("q") or "").strip()
    if len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = contains_folded(
        SystemDocument.objects.all(), "title", q, "doc_title_search"
    )
    titles = list(qs.values_list("title", flat=True)[:8])
    return JsonResponse({"suggestions": titles})


@admin_required
@require_http_methods(["POST"])
def doc_delete(request, pk):
    doc = get_object_or_404(SystemDocument, pk=pk)
    log_event(
        module="system",
        event_type=EventLog.EventType.DELETE,
        user=request.user,
        target=f"doc:{doc.pk}:{doc.title}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    doc.delete()
    messages.success(request, "Документ удалён.")
    return redirect("system:docs")


# ---------------------------------------------------------------------------
# Новости (ТЗ разд. 3.8)
# ---------------------------------------------------------------------------


@login_required
def news_list(request):
    """Карточки новостей с поиском и фильтрами (PRD v3 §2.7)."""
    qs = NewsItem.objects.select_related("author", "category")
    status = request.GET.get("status", "")
    category_slug = request.GET.get("category", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    q = (request.GET.get("q") or "").strip()

    if not _is_admin(request.user) or status == "on":
        qs = qs.filter(is_active=True)
    elif status == "off":
        qs = qs.filter(is_active=False)
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    if date_from:
        try:
            from datetime import datetime

            qs = qs.filter(created_at__date__gte=datetime.strptime(date_from, "%Y-%m-%d").date())
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime

            qs = qs.filter(created_at__date__lte=datetime.strptime(date_to, "%Y-%m-%d").date())
        except ValueError:
            pass

    if q:
        qs = filter_contains_any(
            qs,
            ("title", "summary", "text"),
            q,
            prefix="news_search_",
        )

    page = _paginate(request, qs)
    return render(
        request,
        "system/news.html",
        {
            "page": page,
            "categories": NewsCategory.objects.all(),
            "can_manage": _is_admin(request.user),
            "form": NewsForm(),
            "active_nav": "news",
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def news_create(request):
    """Создание новости: GET редиректит на ленту, форму несёт news.html."""
    if request.method == "GET":
        return redirect("system:news")
    form = NewsForm(request.POST, request.FILES)
    if form.is_valid():
        item = form.save(commit=False)
        item.author = request.user
        item.save()
        log_event(
            module="system",
            event_type=EventLog.EventType.CREATE,
            user=request.user,
            target=f"news:{item.pk}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Новость опубликована.")
    else:
        messages.error(request, "Не удалось опубликовать новость: проверьте форму.")
    return redirect("system:news")


@admin_required
@require_http_methods(["GET", "POST"])
def news_update(request, pk):
    item = get_object_or_404(NewsItem, pk=pk)
    if request.method == "POST":
        form = NewsForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            log_event(
                module="system",
                event_type=EventLog.EventType.UPDATE,
                user=request.user,
                target=f"news:{item.pk}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Новость обновлена.")
            return redirect("system:news")
    else:
        form = NewsForm(instance=item)
    return render(
        request,
        "system/news_form.html",
        {"form": form, "item": item, "title": "Редактирование новости", "active_nav": "news"},
    )


@login_required
def news_detail(request, pk):
    """Детальный просмотр новости с подсчётом просмотров (PRD v3 §2.7)."""
    item = get_object_or_404(
        NewsItem.objects.select_related("author", "category"), pk=pk
    )
    if not item.is_active and not _is_admin(request.user):
        raise Http404
    NewsItem.objects.filter(pk=pk).update(views_count=F("views_count") + 1)
    item.views_count += 1
    return render(
        request,
        "system/news_detail.html",
        {
            "item": item,
            "can_manage": _is_admin(request.user),
            "active_nav": "news",
        },
    )


@login_required
@require_http_methods(["GET"])
def news_cover(request, pk):
    """Отдаёт обложку только пользователям, которым доступна сама новость."""
    item = get_object_or_404(NewsItem, pk=pk)
    if not item.is_active and not _is_admin(request.user):
        raise Http404
    if not item.cover_image:
        raise Http404

    filename = item.cover_image.name.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_handle = open_field_file_or_404(item.cover_image)
    return FileResponse(
        file_handle,
        as_attachment=False,
        filename=filename,
        content_type=content_type,
    )


@login_required
@require_http_methods(["GET"])
def news_suggest(request):
    """Автозаполнение поиска по новостям (PRD v3 §2.0.6)."""
    from django.http import JsonResponse

    q = (request.GET.get("q") or "").strip()
    if len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = NewsItem.objects.all()
    if not _is_admin(request.user):
        qs = qs.filter(is_active=True)
    qs = contains_folded(qs, "title", q, "news_title_search")
    titles = list(qs.values_list("title", flat=True)[:8])
    return JsonResponse({"suggestions": titles})


@admin_required
@require_http_methods(["POST"])
def news_toggle(request, pk):
    item = get_object_or_404(NewsItem, pk=pk)
    item.is_active = not item.is_active
    item.save(update_fields=["is_active"])
    state = "опубликована" if item.is_active else "скрыта"
    messages.success(request, f"Новость «{item.title}» {state}.")
    return redirect("system:news")


@admin_required
@require_http_methods(["POST"])
def news_delete(request, pk):
    item = get_object_or_404(NewsItem, pk=pk)
    log_event(
        module="system",
        event_type=EventLog.EventType.DELETE,
        user=request.user,
        target=f"news:{item.pk}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    item.delete()
    messages.success(request, "Новость удалена.")
    return redirect("system:news")


# ---------------------------------------------------------------------------
# Настройка пользовательского интерфейса (ТЗ разд. 3.2)
# ---------------------------------------------------------------------------


def _tables_meta() -> dict:
    return {
        JOURNAL_TABLE_KEY: {
            "title": "Журнал обращений",
            "columns": JOURNAL_COLUMNS,
            "allowed_sorts": SORTABLE_FIELDS,
        }
    }


@login_required
def prefs_list(request):
    prefs = UserTableViewPref.objects.filter(user=request.user)
    tables = _tables_meta()
    return render(
        request,
        "system/prefs.html",
        {"prefs": prefs, "tables": tables, "active_nav": "prefs"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def table_prefs(request, table_key):
    meta = _tables_meta().get(table_key)
    if meta is None:
        raise Http404
    pref = UserTableViewPref.for_table(
        request.user, table_key, [c["key"] for c in meta["columns"]]
    )
    if request.method == "POST":
        selected = request.POST.getlist("columns")
        default_order = [c["key"] for c in meta["columns"]]
        # Позиции сортируемых колонок (порядок следования)
        position = {}
        for key in default_order:
            raw = request.POST.get(f"order_{key}")
            if raw and raw.isdigit():
                position[key] = int(raw)
        selected_sorted = sorted(
            (k for k in selected if k in default_order),
            key=lambda k: position.get(k, 999),
        )
        sort_field = request.POST.get("sort_field", "")
        sort_dir = request.POST.get("sort_dir", "-")
        if sort_field not in meta["allowed_sorts"]:
            sort_field = ""
        if sort_dir not in ("", "-"):
            sort_dir = "-"
        pref.columns = selected_sorted
        pref.sorting = {"field": sort_field, "dir": sort_dir} if sort_field else {}
        pref.fixed_first = request.POST.get("fixed_first") == "on"
        pref.save()
        log_event(
            module="system",
            event_type=EventLog.EventType.OTHER,
            user=request.user,
            target=f"table_prefs:{table_key}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Настройки таблицы сохранены.")
        return redirect("journal:list")

    current = set(pref.columns or [])
    sorting = pref.sorting or {}
    saved_order = pref.columns or [c["key"] for c in meta["columns"]]
    order_by_key = {key: index for index, key in enumerate(saved_order, start=1)}
    columns = sorted(
        meta["columns"],
        key=lambda column: order_by_key.get(column["key"], len(order_by_key) + 1),
    )
    return render(
        request,
        "system/table_prefs.html",
        {
            "table_key": table_key,
            "meta": meta,
            "columns": columns,
            "order_by_key": order_by_key,
            "current": current,
            "pref": pref,
            "sort_field": sorting.get("field", ""),
            "sort_dir": sorting.get("dir", "-"),
            "active_nav": "prefs",
        },
    )
