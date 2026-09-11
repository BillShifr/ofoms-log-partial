"""Контекст-процессоры: системные параметры для шаблонов."""

from django.conf import settings


def system_meta(request):
    """Передаёт SYSTEM_META, текущую роль, признак администратора и число
    непрочитанных сообщений (для пунктов меню base.html)."""
    from apps.core.roles import ROLE_GROUP_MAP, Roles, role_code_for_user

    user = getattr(request, "user", None)
    role_code = role_code_for_user(user)
    is_admin = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or role_code == Roles.ADMIN)
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

    return {
        "SYSTEM_META": settings.SYSTEM_META,
        "SYSTEM_ROLE": role_code,
        "SYSTEM_ROLE_LABEL": ROLE_GROUP_MAP.get(role_code, ""),
        "can_manage_system": is_admin,
        "unread_messages": unread,
    }
