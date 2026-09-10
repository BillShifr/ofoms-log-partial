import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(value, key):
    if value is None:
        return None
    return value.get(key)


_ALLOWED_TAGS = {"b", "i", "u", "s", "p", "br", "ul", "ol", "li", "h3", "h4", "blockquote"}
_ALLOWED_ATTRS = {"a": {"href"}}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z0-9]+)([^>]*?)(/?)>")
_ATTR_RE = re.compile(r'([a-zA-Z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')


@register.filter
def sanitize_rich(value):
    """Фильтрует «богатый» HTML административного контента по белому списку
    (PRD v3 §2.7): разрешены простые теги оформления и ссылки, всё остальное
    экранируется."""
    if not value:
        return ""

    drop_link_end = [False]

    def _replace(m):
        closing, tag, attrs, self_closing = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tag not in _ALLOWED_TAGS and tag not in _ALLOWED_ATTRS:
            return escape(m.group(0))
        if closing:
            if tag == "a" and drop_link_end[0]:
                drop_link_end[0] = False
                return escape(m.group(0))
            return f"</{tag}>"
        cleaned_attrs = []
        if tag in _ALLOWED_ATTRS:
            for name, dval, sval in _ATTR_RE.findall(attrs):
                name = name.lower()
                val = (dval or sval or "").strip()
                if name in _ALLOWED_ATTRS[tag]:
                    if name == "href":
                        if not val.startswith(("http://", "https://", "mailto:", "/")):
                            continue
                        cleaned_attrs.append(f'href="{escape(val)}" target="_blank" rel="noopener"')
                    else:
                        cleaned_attrs.append(f'{name}="{escape(val)}"')
            if not cleaned_attrs and tag == "a":
                drop_link_end[0] = True
                return ""
        joined = " ".join(cleaned_attrs)
        return f"<{tag}{' ' + joined if joined else ''}{self_closing}>"

    cleaned = _TAG_RE.sub(_replace, value)
    return mark_safe(cleaned)
