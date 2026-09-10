"""Вьюхи отчётов: список, формирование, экспорт Excel/PDF (ТЗ разд. 2.5)."""

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core.models import EventLog, log_event
from apps.reports.export import write_pdf, write_xlsx_bytes
from apps.reports.forms import ReportFilterForm
from apps.reports.reports import REPORT_INDEX, REPORTS

EXPORT_META = {
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        write_xlsx_bytes,
    ),
    "pdf": ("application/pdf", "pdf", write_pdf),
}


def _get_spec(slug):
    spec = REPORT_INDEX.get(slug)
    if spec is None:
        raise Http404
    return spec


@login_required
@require_GET
def reports_index(request):
    return render(
        request,
        "reports/index.html",
        {"reports": REPORTS, "active_nav": "reports"},
    )


@login_required
@require_GET
def report_detail(request, slug):
    spec = _get_spec(slug)
    form = ReportFilterForm(request.GET or None, user=request.user)
    rows = None
    if form.is_valid() and form.has_filters:
        rows = spec.build(request.user.org, form.to_filters())
        log_event(
            module="reports",
            event_type=EventLog.EventType.EXPORT,
            user=request.user,
            target=f"report:{spec.slug}:preview",
            ip=request.META.get("REMOTE_ADDR"),
        )
    return render(
        request,
        "reports/detail.html",
        {
            "report": spec,
            "form": form,
            "rows": rows,
            "active_nav": "reports",
        },
    )


@login_required
@require_GET
def report_export(request, slug, fmt):
    spec = _get_spec(slug)
    if fmt not in EXPORT_META:
        raise Http404
    content_type, extension, writer = EXPORT_META[fmt]
    form = ReportFilterForm(request.GET or None, user=request.user)
    if not form.is_valid():
        return HttpResponse(status=400)
    payload = writer(spec, spec.build(request.user.org, form.to_filters()))
    log_event(
        module="reports",
        event_type=EventLog.EventType.EXPORT,
        user=request.user,
        target=f"report:{spec.slug}:{fmt}",
        ip=request.META.get("REMOTE_ADDR"),
    )
    response = HttpResponse(payload, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="pril{spec.number}_{spec.slug}.{extension}"'
    )
    return response
