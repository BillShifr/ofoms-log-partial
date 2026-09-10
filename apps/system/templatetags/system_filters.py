from html.parser import HTMLParser
from urllib.parse import urlsplit

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
_VOID_TAGS = {"br"}


def _safe_href(value):
    """Разрешает только абсолютный HTTP(S), mailto и локальный single-slash URL."""
    if value.startswith("/") and not value.startswith("//"):
        return True
    parsed = urlsplit(value)
    return (parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)) or (
        parsed.scheme.lower() == "mailto" and bool(parsed.path)
    )


class _RichTextSanitizer(HTMLParser):
    """Строит безопасный HTML из токенов parser, не разбирая HTML regex-ом."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.link_stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            allowed = bool(href and _safe_href(href.strip()))
            self.link_stack.append(allowed)
            if allowed:
                self.parts.append(
                    f'<a href="{escape(href.strip())}" target="_blank" rel="noopener">'
                )
            return
        if tag in _ALLOWED_TAGS:
            self.parts.append(f"<{tag}>")
        else:
            self.parts.append(escape(self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _VOID_TAGS:
            self.parts.append(f"<{tag}>")
        else:
            self.parts.append(escape(self.get_starttag_text()))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a":
            if self.link_stack and self.link_stack.pop():
                self.parts.append("</a>")
            return
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f"</{tag}>")
        elif tag not in _VOID_TAGS:
            self.parts.append(escape(f"</{tag}>"))

    def handle_data(self, data):
        self.parts.append(escape(data))

    def handle_comment(self, data):
        return

    def handle_decl(self, decl):
        self.parts.append(escape(f"<!{decl}>"))

    def unknown_decl(self, data):
        self.parts.append(escape(f"<![{data}]>"))


@register.filter
def sanitize_rich(value):
    """Оставляет простое форматирование и безопасные ссылки в тексте новости."""
    if not value:
        return ""
    sanitizer = _RichTextSanitizer()
    sanitizer.feed(str(value))
    sanitizer.close()
    return mark_safe("".join(sanitizer.parts))
