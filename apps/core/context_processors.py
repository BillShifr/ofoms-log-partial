"""Контекст-процессоры: системные параметры для шаблонов."""

from django.conf import settings


def system_meta(request):
    """Передаёт SYSTEM_META, текущую роль, признак администратора и число
    непрочитанных сообщений (для пунктов меню base.html)."""
    from apps.core.roles import Roles, role_code_for_user

    user = getattr(request, "user", None)
    is_admin = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or role_code_for_user(user) == Roles.ADMIN)
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
        "SYSTEM_ROLE": role_code_for_user(user),
        "can_manage_system": is_admin,
        "unread_messages": unread,
    }
