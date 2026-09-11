"""Экран загрузки файлов обмена (Способ 2/3 регистрации — ТЗ) и протоколов.

Загрузка XML (G1*.xml, users*.xml) и Excel (*.xlsx), единый ФЛК, протокол
обработки (FLCP) с результатом и ошибками доступен участнику обмена.
"""

import os

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import EventLog, log_event
from apps.core.policy import EXCHANGE_READ, EXCHANGE_UPLOAD, user_has_capability
from apps.employee.models import ORGS, TFOMS
from apps.exchange.forms import UploadFileForm
from apps.exchange.importers import (
    EmployeeXMLFile,
    ExcelIrpFile,
    IrpXMLFile,
    write_unique_artifact,
)
from apps.exchange.models import ImportLog


def _allowed_orgs(user):
    """СМО — только своя организация; ТФОМС/админ — все."""
    if user.org == TFOMS or user.is_superuser:
        return [(o[0], str(o[1])) for o in ORGS]
    return [(user.org, str(dict(ORGS)[user.org]))]


@login_required
@require_http_methods(["GET", "POST"])
def exchange_upload(request):
    if not user_has_capability(request.user, EXCHANGE_UPLOAD):
        raise PermissionDenied
    form = UploadFileForm(
        user=request.user, org_choices=_allowed_orgs(request.user)
    )
    if request.method == "POST":
        form = UploadFileForm(
            request.POST, request.FILES, user=request.user,
            org_choices=_allowed_orgs(request.user),
        )
        if form.is_valid():
            org = int(form.cleaned_data["org"])
            uploaded = request.FILES["file"]
            with transaction.atomic():
                log = _process_upload(request.user, org, uploaded)
                log_event(
                    module="exchange",
                    event_type=EventLog.EventType.CREATE,
                    user=request.user,
                    target=f"import:{log.pk}:{log.filename}",
                    ip=request.META.get("REMOTE_ADDR"),
                )
            return redirect("exchange:protocol", pk=log.pk)
    return render(
        request,
        "exchange/upload.html",
        {"form": form, "active_nav": "exchange"},
    )


def _process_upload(user, org, uploaded) -> ImportLog:
    from django.conf import settings

    # Безопасное имя файла (без путей) — только имя
    safe_name = os.path.basename(uploaded.name or "file")
    in_org = settings.EXCHANGE_IN / str(org)
    dest = write_unique_artifact(in_org / safe_name, uploaded.chunks())

    name_lower = safe_name.lower()
    if name_lower.startswith("users") and name_lower.endswith(".xml"):
        importer = EmployeeXMLFile(org, dest)
    elif name_lower.startswith("g1") and name_lower.endswith(".xml"):
        importer = IrpXMLFile(org, dest)
    elif name_lower.endswith(".xlsx"):
        importer = ExcelIrpFile(org, dest)
    else:
        raise ValueError(
            "Неизвестный тип файла: ожидается G1*.xml, users*.xml или *.xlsx"
        )

    result = importer.process()
    importer.write_flcp(result)
    log = ImportLog.objects.create(
        org=org,
        kind=result.kind,
        filename=result.filename,
        status=ImportLog.Status.ERROR if not result.ok else ImportLog.Status.OK,
        rows=result.rows,
        flcp=result.flcp_bytes().decode("windows-1251", errors="replace"),
    )
    return log


@login_required
def exchange_logs(request):
    if not user_has_capability(request.user, EXCHANGE_READ):
        raise PermissionDenied
    qs = ImportLog.objects.all()
    if request.user.org != TFOMS and not request.user.is_superuser:
        qs = qs.filter(org=request.user.org)
    logs = qs[:100]
    return render(
        request,
        "exchange/logs.html",
        {"logs": logs, "active_nav": "exchange"},
    )


@login_required
def exchange_protocol(request, pk):
    if not user_has_capability(request.user, EXCHANGE_READ):
        raise PermissionDenied
    log = get_object_or_404(ImportLog, pk=pk)
    if (
        request.user.org != TFOMS
        and not request.user.is_superuser
        and log.org != request.user.org
    ):
        raise PermissionDenied
    rows = _parse_flcp(log.flcp)
    return render(
        request,
        "exchange/protocol.html",
        {"log": log, "prs": rows, "active_nav": "exchange"},
    )


def _parse_flcp(text: str) -> list[dict]:
    """FLCP (XML) -> список записей протокола для отображения."""
    try:
        from lxml import etree

        root = etree.fromstring(text.encode("windows-1251"))
    except Exception:
        return []
    return [dict(el.attrib) for el in root.iter("PR")]
