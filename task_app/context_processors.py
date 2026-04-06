from django.db.utils import OperationalError, ProgrammingError

from .access import get_user_organization, get_user_role


def current_user_access(request):
    user = getattr(request, "user", None)
    default_context = {
        "current_user_role": None,
        "current_user_role_label": None,
        "current_user_organization": None,
    }

    if not getattr(user, "is_authenticated", False):
        return default_context

    try:
        role = get_user_role(user)
        organization = get_user_organization(user)
    except (OperationalError, ProgrammingError):
        return default_context

    role_labels = {
        "ADMIN": "Administrator",
        "MANAGER": "Manager",
        "MEMBER": "Member",
    }

    return {
        "current_user_role": role,
        "current_user_role_label": role_labels.get(role, role),
        "current_user_organization": organization,
    }