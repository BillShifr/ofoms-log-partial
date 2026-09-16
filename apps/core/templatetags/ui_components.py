"""Shared, server-rendered UI components used across portal modules."""

from django import template
from django.template.base import token_kwargs
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

class DataTableNode(template.Node):
    """Render the common table shell while allowing arbitrary row markup."""

    def __init__(self, nodelist, options):
        self.nodelist = nodelist
        self.options = options

    def render(self, context):
        options = {
            key: expression.resolve(context)
            for key, expression in self.options.items()
        }
        label = str(options.get("label", "")).strip()
        table_key = str(options.get("table_key", "")).strip()
        title = str(options.get("title", "")).strip()
        settings_url = str(options.get("settings_url", "")).strip()
        responsive = bool(options.get("responsive", False))
        sortable = bool(options.get("sortable", False))
        fixed_first = bool(options.get("fixed_first", False))
        scrollable = bool(options.get("scrollable", True))
        settings_enabled = bool(options.get("settings", True))
        has_settings = bool(table_key and title and settings_enabled)

        table_classes = ["data"]
        if responsive:
            table_classes.append("data--responsive")
        if fixed_first:
            table_classes.append("th-sticky")

        table_attrs = format_html(' class="{}"', " ".join(table_classes))
        if sortable:
            table_attrs = format_html("{} data-client-sort", table_attrs)
        if table_key:
            table_attrs = format_html('{} data-table-key="{}"', table_attrs, table_key)
        content = self.nodelist.render(context)
        table_markup = format_html("<table{}>{}</table>", table_attrs, mark_safe(content))
        if not scrollable:
            return table_markup

        wrap_classes = ["table-wrap"]
        if responsive:
            wrap_classes.append("table-wrap--responsive")
        wrapped_table = format_html(
            '<div class="{}" tabindex="0" aria-label="{}">{}</div>',
            " ".join(wrap_classes),
            label,
            table_markup,
        )
        if not title:
            return wrapped_table

        safe_key = "".join(ch if ch.isalnum() else "-" for ch in table_key) or "table"
        modal_id = f"table-settings-{safe_key}"
        settings_button = ""
        settings_modal = ""
        if has_settings:
            settings_button = format_html(
                '<button class="btn btn--ghost btn--icon table-settings__trigger" '
                'type="button" data-table-settings-trigger data-modal-target="{}" '
                'data-table-key="{}" data-settings-url="{}" '
                'aria-label="Настроить таблицу {}" title="Настроить таблицу">'
                '<span aria-hidden="true">⚙</span></button>',
                modal_id,
                table_key,
                settings_url,
                title,
            )
            server_settings = ""
            if settings_url:
                server_settings = format_html(
                    '<div class="table-settings__server" data-table-settings-content>'
                    '<p class="text-muted">Загрузка настроек колонок...</p></div>'
                )
            settings_modal = format_html(
                '<dialog class="modal table-settings-modal" id="{}">'
                '<div class="modal__dialog">'
                '<div class="modal__head"><h2>Настройки таблицы</h2>'
                '<form method="dialog"><button class="btn btn--ghost btn--icon" '
                'type="submit" aria-label="Закрыть настройки">×</button></form></div>'
                '<div class="modal__body">'
                '<div class="table-settings__local">'
                '<p class="text-muted">Ширины колонок сохраняются в этом браузере для текущей таблицы.</p>'
                '<button class="btn btn--ghost" type="button" data-table-reset-widths '
                'data-table-key="{}">Сбросить ширины колонок</button>'
                '</div>{}</div></div></dialog>',
                modal_id,
                table_key,
                server_settings,
            )
        toolbar = format_html(
            '<div class="table-toolbar" aria-label="Действия с таблицей {}">'
            '<p class="table-toolbar__title">{}</p>{}</div>',
            title,
            title,
            settings_button,
        )
        return format_html("{}{}{}", toolbar, settings_modal, wrapped_table)


@register.tag("data_table")
def do_data_table(parser, token):
    """Wrap table markup in the portal's canonical table component.

    Usage::

        {% data_table responsive=True sortable=True table_key="users" label="Users" %}
          <thead>...</thead><tbody>...</tbody>
        {% end_data_table %}
    """

    bits = token.split_contents()[1:]
    options = token_kwargs(bits, parser)
    if bits:
        raise template.TemplateSyntaxError(
            "data_table arguments must use the name=value form"
        )

    allowed = {
        "label",
        "table_key",
        "responsive",
        "sortable",
        "fixed_first",
        "scrollable",
        "title",
        "settings_url",
        "settings",
    }
    unknown = set(options) - allowed
    if unknown:
        raise template.TemplateSyntaxError(
            f"unknown data_table argument: {sorted(unknown)[0]}"
        )

    nodelist = parser.parse(("end_data_table",))
    parser.delete_first_token()
    return DataTableNode(nodelist, options)
