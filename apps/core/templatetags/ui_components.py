"""Shared, server-rendered UI components used across portal modules."""

from django import template
from django.template.base import token_kwargs
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

TABLE_VARIANTS = frozenset(
    {
        "capabilities",
        "events",
        "exchange",
        "journal",
        "letter",
        "protocol",
        "reports",
        "tasks",
        "users",
        "wide",
    }
)
TABLE_WRAP_VARIANTS = frozenset({"journal", "tasks"})


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
        variant = str(options.get("variant", "")).strip()
        wrap_variant = str(options.get("wrap_variant", "")).strip()
        label = str(options.get("label", "")).strip()
        table_key = str(options.get("table_key", "")).strip()
        responsive = bool(options.get("responsive", False))
        sortable = bool(options.get("sortable", False))
        fixed_first = bool(options.get("fixed_first", False))
        scrollable = bool(options.get("scrollable", True))

        variants = variant.split()
        unknown_variants = set(variants) - TABLE_VARIANTS
        if unknown_variants:
            raise template.TemplateSyntaxError(
                f"unknown data_table variant: {sorted(unknown_variants)[0]}"
            )
        wrap_variants = wrap_variant.split()
        unknown_wrap_variants = set(wrap_variants) - TABLE_WRAP_VARIANTS
        if unknown_wrap_variants:
            raise template.TemplateSyntaxError(
                f"unknown data_table wrap variant: {sorted(unknown_wrap_variants)[0]}"
            )

        table_classes = ["data"]
        table_classes.extend(f"data--{name}" for name in variants)
        if responsive:
            table_classes.append("data--responsive")
        if fixed_first:
            table_classes.append("th-sticky")

        table_attrs = format_html(' class="{}"', " ".join(table_classes))
        if table_key:
            table_attrs = format_html('{} data-table-key="{}"', table_attrs, table_key)
        if sortable:
            table_attrs = format_html("{} data-client-sort", table_attrs)
        content = self.nodelist.render(context)
        table_markup = format_html("<table{}>{}</table>", table_attrs, mark_safe(content))
        if not scrollable:
            return table_markup

        wrap_classes = ["table-wrap"]
        wrap_classes.extend(f"table-wrap--{name}" for name in wrap_variants)
        if responsive:
            wrap_classes.append("table-wrap--responsive")
        return format_html(
            '<div class="{}" tabindex="0" aria-label="{}">{}</div>',
            " ".join(wrap_classes),
            label,
            table_markup,
        )


@register.tag("data_table")
def do_data_table(parser, token):
    """Wrap table markup in the portal's canonical table component.

    Usage::

        {% data_table variant="users" responsive=True sortable=True label="Users" %}
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
        "variant",
        "wrap_variant",
        "label",
        "table_key",
        "responsive",
        "sortable",
        "fixed_first",
        "scrollable",
    }
    unknown = set(options) - allowed
    if unknown:
        raise template.TemplateSyntaxError(
            f"unknown data_table argument: {sorted(unknown)[0]}"
        )

    nodelist = parser.parse(("end_data_table",))
    parser.delete_first_token()
    return DataTableNode(nodelist, options)
