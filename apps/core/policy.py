"""Central deny-by-default capability policy for regulated business actions."""

from apps.core.roles import GROUP_ROLE_MAP, Roles

JOURNAL_CREATE = "journal.create"
JOURNAL_CHANGE = "journal.change"
JOURNAL_REDIRECT = "journal.redirect"
JOURNAL_READ = "journal.read"
EXCHANGE_UPLOAD = "exchange.upload"
EXCHANGE_READ = "exchange.read"
REPORTS_READ = "reports.read"

ALL_ROLES = {
    Roles.OP1,
    Roles.OP2,
    Roles.SP1,
    Roles.SP2,
    Roles.SP3,
    Roles.ADMIN,
    Roles.CALL_ADMIN,
}

CAPABILITY_ROLES = {
    JOURNAL_READ: ALL_ROLES,
    JOURNAL_CREATE: {Roles.OP1, Roles.SP1, Roles.ADMIN},
    JOURNAL_CHANGE: {
        Roles.OP1,
        Roles.OP2,
        Roles.SP1,
        Roles.SP2,
        Roles.SP3,
        Roles.ADMIN,
    },
    JOURNAL_REDIRECT: {Roles.OP1, Roles.SP1, Roles.ADMIN},
    EXCHANGE_UPLOAD: {Roles.OP1, Roles.SP1, Roles.ADMIN},
    EXCHANGE_READ: ALL_ROLES,
    REPORTS_READ: ALL_ROLES,
}


def role_codes_for_user(user) -> set[int]:
    if user is None or not user.is_authenticated:
        return set()
    return {
        code
        for name in user.groups.values_list("name", flat=True)
        if (code := GROUP_ROLE_MAP.get(name)) is not None
    }


def user_has_capability(user, capability: str) -> bool:
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    allowed = CAPABILITY_ROLES.get(capability)
    return allowed is not None and bool(role_codes_for_user(user) & allowed)
