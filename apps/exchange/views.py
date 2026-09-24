"""Экран загрузки файлов обмена (Способ 2/3 регистрации — ТЗ) и протоколов.

Загрузка XML (G1*.xml, users*.xml) и Excel (*.xlsx), единый ФЛК, протокол
обработки (FLCP) с результатом и ошибками доступен участнику обмена.
"""

import os
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_safe

from apps.core.models import EventLog, log_event
from apps.core.policy import EXCHANGE_READ, EXCHANGE_UPLOAD, user_has_capability
from apps.employee.models import ORGS, TFOMS
from apps.exchange.forms import UploadFileForm
from apps.exchange.importers import (
    ArtifactRollback,
    EmployeeXMLFile,
    ExcelIrpFile,
    IrpXMLFile,
    write_unique_artifact,
)
from apps.exchange.models import ImportLog
from apps.exchange.outbound import (
    CONTRACT_FILENAME,
    CONTRACT_MARKER,
    build_outbound_package,
)
from apps.journal.models import Irp

LOG_PAGE_SIZE = 25


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
            with ArtifactRollback() as artifacts, transaction.atomic():
                log = _process_upload(request.user, org, uploaded, artifacts)
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


def _process_upload(user, org, uploaded, artifacts: ArtifactRollback) -> ImportLog:
    from django.conf import settings

    # Безопасное имя файла (без путей) — только имя
    safe_name = os.path.basename(uploaded.name or "file")
    in_org = settings.EXCHANGE_IN / str(org)
    dest = write_unique_artifact(in_org / safe_name, uploaded.chunks())
    artifacts.track(dest)

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
    artifacts.track(importer.archived_path)
    protocol_path = importer.write_flcp(result)
    artifacts.track(protocol_path)
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
@require_safe
def exchange_logs(request):
    if not user_has_capability(request.user, EXCHANGE_READ):
        raise PermissionDenied
    qs = ImportLog.objects.all()
    if request.user.org != TFOMS and not request.user.is_superuser:
        qs = qs.filter(org=request.user.org)
    paginator = Paginator(qs, LOG_PAGE_SIZE)
    try:
        page = paginator.page(int(request.GET.get("page", 1)))
    except (EmptyPage, ValueError):
        page = paginator.page(paginator.num_pages)
    logs = list(page.object_list)
    for log in logs:
        protocol_rows = _parse_flcp(log.flcp) or []
        log.error_rows = [row for row in protocol_rows if row.get("OSHIB") != "0"]
        log.error_count = len(log.error_rows)
    return render(
        request,
        "exchange/logs.html",
        {"logs": logs, "page": page, "active_nav": "exchange"},
    )


@login_required
@require_safe
def exchange_export(request):
    """Выгружает обращения по внутреннему контракту текущего формата G1."""
    if not user_has_capability(request.user, EXCHANGE_READ):
        raise PermissionDenied
    allowed = {code for code, _ in _allowed_orgs(request.user)}
    try:
        org = int(request.GET.get("org", request.user.org))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Некорректная организация")
    if org not in allowed:
        raise PermissionDenied

    qs = Irp.objects.select_related(
        "theme", "employee_one", "employee_it"
    ).filter(employee_one__org=org)
    for parameter, lookup in (("date_from", "date_create__gte"), ("date_to", "date_create__lte")):
        raw = request.GET.get(parameter)
        if not raw:
            continue
        value = parse_date(raw)
        if value is None:
            return HttpResponseBadRequest(f"Некорректная дата: {parameter}")
        qs = qs.filter(**{lookup: value})
    qs = qs.order_by("date_create", "pk")
    count = qs.count()
    generated_at = timezone.now()
    if timezone.is_aware(generated_at):
        generated_at = timezone.localtime(generated_at)
    generated_at = generated_at.replace(microsecond=0)
    payload = build_outbound_package(qs, org=org, generated_at=generated_at)
    filename = f"G1OUT_{org}_{generated_at:%Y%m%d%H%M%S}.xml"
    log_event(
        module="exchange",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target=f"outbound:{CONTRACT_MARKER}:{org}",
        ip=request.META.get("REMOTE_ADDR"),
        detail=f"Выгружено обращений: {count}",
    )
    response = HttpResponse(payload, content_type="application/xml")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Exchange-Contract"] = CONTRACT_MARKER
    return response


@login_required
@require_safe
def exchange_export_contract(request):
    """Возвращает XSD внутреннего, а не официального обменного контракта."""
    if not user_has_capability(request.user, EXCHANGE_READ):
        raise PermissionDenied
    path = Path(__file__).with_name("contracts") / CONTRACT_FILENAME
    response = HttpResponse(path.read_bytes(), content_type="application/xml")
    response["Content-Disposition"] = f'attachment; filename="{CONTRACT_FILENAME}"'
    response["X-Exchange-Contract"] = CONTRACT_MARKER
    return response


@login_required
@require_safe
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
    if rows:
        numbers = {
            str(row.get("N_ZAP")).strip()
            for row in rows
            if row.get("N_ZAP")
        }
        irps = Irp.objects.filter(n_irp__in=numbers).only("pk", "n_irp", "employee_one")
        if request.user.org != TFOMS and not request.user.is_superuser:
            irps = irps.filter(employee_one__org=request.user.org)
        irp_by_number = {irp.n_irp: irp.pk for irp in irps}
        for row in rows:
            number = str(row.get("N_ZAP") or "").strip()
            if number in irp_by_number:
                row["IRP_PK"] = irp_by_number[number]
    protocol_groups = []
    grouped = {}
    for row in rows or []:
        code = row.get("OSHIB") or "41"
        if code not in grouped:
            grouped[code] = {"code": code, "rows": []}
            protocol_groups.append(grouped[code])
        grouped[code]["rows"].append(row)
    return render(
        request,
        "exchange/protocol.html",
        {
            "log": log,
            "prs": rows or [],
            "protocol_groups": protocol_groups,
            "protocol_unavailable": rows is None,
            "active_nav": "exchange",
        },
    )


def _parse_flcp(text: str) -> list[dict] | None:
    """FLCP (XML) -> список записей протокола для отображения."""
    if not text or not text.strip():
        return None
    try:
        from lxml import etree

        parser = etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            huge_tree=False,
            recover=False,
        )
        root = etree.fromstring(text.encode("windows-1251"), parser=parser)
        if etree.QName(root).localname != "FLCP":
            return None
        return [
            dict(el.attrib)
            for el in root.iterchildren()
            if etree.QName(el).localname == "PR"
        ]
    except (UnicodeError, ValueError, etree.XMLSyntaxError):
        return None
