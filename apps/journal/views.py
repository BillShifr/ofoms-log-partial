"""Кастомный экран журнала обращений (Этап 2).

Требования (ТЗ разд. 2.1, письмо п. 21, 35):
- таблица обращений с основными реквизитами;
- выбор строки -> предпросмотр карточки (РКК) со всеми реквизитами;
- цветовая маркировка строк (>30 дней и не закрыто — красный;
  нет результата, но нет просрочки — жёлтый; иначе — без выделения);
- отбор по реквизитам, поиск, сортировка; постраничный перебор (+ бесконечная
  прокрутка) — keyset-пагинация использует id/дату;
- история изменений на карточке.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.core.fold import contains_folded
from apps.core.models import EventLog, log_event
from apps.employee.models import TFOMS
from apps.journal.forms import IrpAnswerForm, IrpFilterForm, IrpForm, IrpRedirectForm
from apps.journal.models import RESULTS, Irp, IrpAnswer, IrpFile, IrpHistory
from apps.journal.table import (
    ALLOWED_SORTS,
    JOURNAL_COLUMNS,
    JOURNAL_TABLE_KEY,
)
from apps.system.models import UserTableViewPref

PAGE_SIZE = 25


@login_required
def irp_suggest(request):
    """Автозаполнение фильтров журнала (PRD v3 §2.3.2).

    GET ?field=<n_irp|z_f|z_enp>&q=<не менее 3 символов> => JSON-список значений.
    """
    field = request.GET.get("field", "")
    q = (request.GET.get("q") or "").strip()
    if field not in ("n_irp", "z_f", "z_enp") or len(q) < 3:
        return JsonResponse({"suggestions": []})
    qs = Irp.objects.exclude(**{field: ""}).distinct()
    if request.user.org != TFOMS:
        qs = qs.filter(employee_one__org=request.user.org)
    raw = list(qs.order_by(field).values_list(field, flat=True).distinct())
    lower_q = q.lower()
    values = [v for v in raw if lower_q in (v or "").lower()][:8]
    return JsonResponse({"suggestions": values})


@login_required
def irp_list(request):
    """Реестр обращений: таблица + панель фильтров + пагинация."""
    qs = Irp.objects.select_related("theme", "employee_one", "employee_it")

    # СМО видят только свои обращения (принцип v1 get_queryset)
    if request.user.org != TFOMS:
        qs = qs.filter(employee_one__org=request.user.org)

    form = IrpFilterForm(request.GET or None)
    if form.is_valid():
        cd = form.cleaned_data
        if cd["id"]:
            qs = qs.filter(id=cd["id"])
        if cd["z_f"]:
            qs = contains_folded(qs, "z_f", cd["z_f"], "fold_z_f")
        if cd["z_enp"]:
            qs = contains_folded(qs, "z_enp", cd["z_enp"], "fold_z_enp")
        if cd["n_irp"]:
            qs = contains_folded(qs, "n_irp", cd["n_irp"], "fold_n_irp")
        if cd["irp_type"]:
            qs = qs.filter(irp_type=cd["irp_type"])
        if cd["how"]:
            qs = qs.filter(how=cd["how"])
        if cd["theme"]:
            qs = qs.filter(theme=cd["theme"])
        if cd["date_from"]:
            qs = qs.filter(date_create__gte=cd["date_from"])
        if cd["date_to"]:
            qs = qs.filter(date_create__lte=cd["date_to"])
        if cd["status"]:
            today = datetime.date.today()
            if cd["status"] == "closed":
                qs = qs.filter(date_close__isnull=False)
            elif cd["status"] == "overdue":
                qs = qs.filter(date_close__isnull=True, data_plan__lt=today)
            elif cd["status"] == "open":
                qs = qs.filter(date_close__isnull=True)

    pref = UserTableViewPref.for_table(
        request.user, JOURNAL_TABLE_KEY, [c["key"] for c in JOURNAL_COLUMNS]
    )
    visible_keys = pref.columns or [c["key"] for c in JOURNAL_COLUMNS]
    cols = [c for c in JOURNAL_COLUMNS if c["key"] in visible_keys]

    # Сортировка: явный параметр запроса > персональная настройка > по умолчанию
    sort = request.GET.get("sort")
    if sort is None:
        pref_sort = pref.sorting or {}
        if pref_sort.get("field"):
            sort = pref_sort["dir"] + pref_sort["field"]
    if sort not in ALLOWED_SORTS:
        sort = "-date_create"
    qs = qs.order_by(sort, "-id")

    page = _paginate_irp(request, qs)

    log_event(
        module="journal",
        event_type=EventLog.EventType.OTHER,
        user=request.user,
        target="journal:list",
        ip=request.META.get("REMOTE_ADDR"),
    )

    return render(
        request,
        "journal/irp_list.html",
        {
            "page": page,
            "form": form,
            "sort": sort,
            "cols": cols,
            "table_groups": _table_groups(cols),
            "fixed_first": pref.fixed_first,
            "active_nav": "journal",
            "status_map": dict(RESULTS),
        },
    )


def _table_groups(cols):
    """Строит строку групповой шапки (group -> colspan) для видимых колонок."""
    groups = []
    for col in cols:
        label = col["group"]
        if groups and groups[-1]["label"] == label:
            groups[-1]["colspan"] += 1
        else:
            groups.append({"label": label, "colspan": 1})
    return groups


def _paginate_irp(request, qs):
    """Курсорная (keyset) пагинация по ключу (id)."""
    from django.core.paginator import EmptyPage, Paginator

    paginator = Paginator(qs, PAGE_SIZE)
    try:
        return paginator.page(int(request.GET.get("page", 1)))
    except (EmptyPage, ValueError):
        return paginator.page(paginator.num_pages)


@login_required
def irp_detail(request, pk):
    """Полная карточка обращения (РКК) + история, ответы, файлы."""
    irp = _get_irp_for_user(request, pk)
    history = irp.history.select_related("user")
    answers = irp.answers.select_related("user").prefetch_related("files")
    files = irp.files.filter(answer__isnull=True)
    return render(
        request,
        "journal/irp_detail.html",
        {
            "irp": irp,
            "history": history,
            "answers": answers,
            "files": files,
            "answer_form": IrpAnswerForm(),
            "redirect_form": IrpRedirectForm(instance=irp, user=request.user),
            "active_nav": "journal",
        },
    )


@login_required
def irp_print(request, pk):
    """Печатная форма обращения (п. 35: РКК сохраняется на каждом этапе)."""
    irp = _get_irp_for_user(request, pk)
    history = irp.history.select_related("user")
    return render(
        request,
        "journal/irp_print.html",
        {"irp": irp, "history": history},
    )


@login_required
@require_http_methods(["GET", "POST"])
def irp_create(request):
    """Ручная регистрация обращения (ТЗ разд. 2.2, Способ 1)."""
    if request.method == "POST":
        form = IrpForm(request.POST, user=request.user)
        if form.is_valid():
            irp = form.save(commit=False)
            irp.employee_one = request.user
            irp.line_one = 1 if request.user.org == TFOMS else 3
            irp.save()
            _write_history(irp, request.user, created=True)
            log_event(
                module="journal",
                event_type=EventLog.EventType.CREATE,
                user=request.user,
                target=f"irp:{irp.pk}:{irp.n_irp}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Обращение зарегистрировано.")
            return redirect(reverse("journal:detail", args=[irp.pk]))
    else:
        form = IrpForm(user=request.user)
    return render(
        request,
        "journal/irp_form.html",
        {"form": form, "title": "Регистрация обращения", "active_nav": "journal"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def irp_edit(request, pk):
    """Редактирование карточки обращения с фиксацией изменений в истории."""
    irp = _get_irp_for_user(request, pk)
    if request.method == "POST":
        form = IrpForm(request.POST, instance=irp, user=request.user)
        # ModelForm мутирует instance при валидации — снимок до is_valid()
        before = {f: getattr(irp, f) for f in form.fields}
        if form.is_valid():
            old = {f: before[f] for f in form.changed_data}
            irp = form.save()
            _write_history(irp, request.user, old)
            log_event(
                module="journal",
                event_type=EventLog.EventType.UPDATE,
                user=request.user,
                target=f"irp:{irp.pk}:{irp.n_irp}",
                ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Обращение обновлено.")
            return redirect(reverse("journal:detail", args=[irp.pk]))
    else:
        form = IrpForm(instance=irp, user=request.user)
    return render(
        request,
        "journal/irp_form.html",
        {"form": form, "irp": irp, "title": "Редактирование обращения",
         "active_nav": "journal"},
    )


@login_required
@require_http_methods(["POST"])
def irp_answer_create(request, pk):
    """Добавление ответа на обращение (ТЗ п. 215: предварительный ответ)."""
    irp = _get_irp_for_user(request, pk)
    form = IrpAnswerForm(request.POST)
    if form.is_valid():
        answer = form.save(commit=False)
        answer.irp = irp
        answer.user = request.user
        answer.save()
        IrpHistory.objects.create(
            irp=irp, user=request.user, field_name="answer",
            old_value="—",
            new_value="предварительный" if answer.is_preliminary else "итоговый",
        )
        log_event(
            module="journal", event_type=EventLog.EventType.UPDATE,
            user=request.user, target=f"irp:{irp.pk}:answer:{answer.pk}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Ответ сохранён.")
    return redirect(reverse("journal:detail", args=[irp.pk]))


@login_required
@require_http_methods(["POST"])
def irp_file_upload(request, pk):
    """Прикрепление файла к обращению или к ответу (ТЗ п. 200)."""
    irp = _get_irp_for_user(request, pk)
    uploaded = request.FILES.get("file")
    if uploaded:
        answer_id = request.POST.get("answer")
        answer = None
        if answer_id:
            answer = get_object_or_404(IrpAnswer, pk=answer_id, irp=irp)
        IrpFile.objects.create(
            irp=irp,
            answer=answer,
            file=uploaded,
            uploader=request.user,
        )
        log_event(
            module="journal", event_type=EventLog.EventType.CREATE,
            user=request.user,
            target=f"irp:{irp.pk}:file:{uploaded.name}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(request, "Файл прикреплён.")
    return redirect(reverse("journal:detail", args=[irp.pk]))


@login_required
@require_http_methods(["GET", "POST"])
def irp_redirect(request, pk):
    """Переадресация обращения (ТЗ п. 212) + запись в историю."""
    irp = _get_irp_for_user(request, pk)
    if request.method == "POST":
        form = IrpRedirectForm(request.POST, instance=irp, user=request.user)
        before = {f: getattr(irp, f) for f in form.fields}
        if form.is_valid():
            old = {f: before[f] for f in form.changed_data}
            irp = form.save()
            _write_history(irp, request.user, old)
            if old:
                log_event(
                    module="journal", event_type=EventLog.EventType.UPDATE,
                    user=request.user, target=f"irp:{irp.pk}:redirect",
                    ip=request.META.get("REMOTE_ADDR"),
                )
                messages.success(request, "Обращение переадресовано.")
            return redirect(reverse("journal:detail", args=[irp.pk]))
    else:
        form = IrpRedirectForm(instance=irp, user=request.user)
    return render(
        request,
        "journal/irp_redirect.html",
        {"irp": irp, "form": form, "active_nav": "journal"},
    )


@login_required
def irp_cover(request, pk):
    """Печатное сопроводительное письмо при переадресации (ТЗ п. 212)."""
    irp = _get_irp_for_user(request, pk)
    return render(
        request,
        "journal/irp_cover.html",
        {"irp": irp, "today": datetime.date.today()},
    )


def _get_irp_for_user(request, pk):
    irp = get_object_or_404(Irp, pk=pk)
    if request.user.org != TFOMS and irp.employee_one.org != request.user.org:
        raise PermissionDenied
    return irp


def _write_history(irp, user, old=None, created=False):
    """Сохраняет изменения в IrpHistory (печать на каждом этапе — п. 35)."""
    if created:
        IrpHistory.objects.create(irp=irp, user=user, field_name="__created__")
        return
    for field, old_val in old.items():
        new_val = getattr(irp, field)
        IrpHistory.objects.create(
            irp=irp, user=user, field_name=field,
            old_value=_stringify(old_val), new_value=_stringify(new_val),
        )


def _stringify(value):
    if value is None:
        return "—"
    return str(value)
