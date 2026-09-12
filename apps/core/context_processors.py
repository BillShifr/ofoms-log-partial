"""Контекст-процессоры: системные параметры для шаблонов."""

from django.conf import settings


def system_meta(request):
    """Передаёт SYSTEM_META, текущую роль, признак администратора и число
    непрочитанных сообщений (для пунктов меню base.html)."""
    from apps.core.policy import role_codes_for_user
    from apps.core.roles import ROLE_CHOICES, ROLE_GROUP_MAP, Roles

    user = getattr(request, "user", None)
    role_codes = role_codes_for_user(user)
    role_code = next(
        (code for code, _label in ROLE_CHOICES if code in role_codes), None
    )
    is_admin = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or Roles.ADMIN in role_codes)
    )
    unread = 0
    if user is not None and user.is_authenticated:
        from apps.system.models import MessageReply

        unread = (
            MessageReply.objects.filter(thread__conversation__participants=user)
            .exclude(author=user)
            .exclude(read_by=user)
            .values("thread__conversation_id")
            .distinct()
            .count()
        )

    role_label = ", ".join(
        ROLE_GROUP_MAP[code] for code, _label in ROLE_CHOICES if code in role_codes
    )
    if user and user.is_authenticated and user.is_superuser and not role_label:
        role_label = "Суперпользователь"

    return {
        "SYSTEM_META": settings.SYSTEM_META,
        "SYSTEM_ROLE": role_code,
        "SYSTEM_ROLE_LABEL": role_label,
        "can_manage_system": is_admin,
        "unread_messages": unread,
    }
