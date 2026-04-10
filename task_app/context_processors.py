"""Context processors used by the shared base templates."""

from django.db.utils import OperationalError, ProgrammingError

from .access import get_user_organization, get_user_organizations, get_user_role


def current_user_access(request):
    """Expose the current user's scoped access details to all templates.

    The database exception handling is intentional. It allows pages to render
    during first-run migration states where the profile tables may not exist yet.
    """
    user = getattr(request, "user", None)
    default_context = {
        "current_user_role": None,
        "current_user_role_label": None,
        "current_user_organization": None,
        "current_user_organizations": [],
    }

    if not getattr(user, "is_authenticated", False):
        return default_context

    try:
        role = get_user_role(user)
        organization = get_user_organization(user)
        organizations = list(get_user_organizations(user))
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
        "current_user_organizations": organizations,
    }
