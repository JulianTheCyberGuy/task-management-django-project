"""Centralized role and queryset scoping helpers for the task management app.

These helpers keep authorization rules in one place so both the HTML views and
API views enforce the same access boundaries. That makes the project easier to
reason about and reduces the risk of one interface exposing more data than
another.
"""

from django.contrib.auth import get_user_model

from .models import Organization, Project, Task


ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_MEMBER = "MEMBER"
MANAGE_ROLES = {ROLE_ADMIN, ROLE_MANAGER}


User = get_user_model()


def get_user_role(user):
    """Resolve the effective application role for the current user.

    Superusers are treated as app administrators even if their profile is
    missing or misconfigured so the Django admin and app admin behavior stay in
    sync.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_ADMIN

    profile = getattr(user, "profile", None)
    if profile and profile.role:
        return profile.role
    # Defaulting to MEMBER avoids granting elevated access when profile data is incomplete.
    return ROLE_MEMBER


def get_user_organizations(user):
    """Return all organizations the user can access.

    The app keeps a primary organization for display and compatibility, while
    the many-to-many membership list drives actual visibility rules.
    """
    if not user.is_authenticated or user.is_superuser:
        return Organization.objects.none()

    profile = getattr(user, "profile", None)
    if profile is None:
        return Organization.objects.none()

    memberships = profile.organizations.all().order_by("name")
    if memberships.exists():
        return memberships

    primary_organization = getattr(profile, "organization", None)
    if primary_organization is None:
        return Organization.objects.none()

    return Organization.objects.filter(pk=primary_organization.pk)


def get_user_organization(user):
    """Return the user's primary scoped organization, if one exists."""
    if not user.is_authenticated or user.is_superuser:
        return None

    profile = getattr(user, "profile", None)
    if profile is None:
        return None

    if profile.organization_id:
        return profile.organization

    return get_user_organizations(user).first()


def can_manage_app(user):
    """Managers and administrators can create and edit shared business data."""
    return get_user_role(user) in MANAGE_ROLES


def is_admin(user):
    """Small wrapper used throughout the project for readability."""
    return get_user_role(user) == ROLE_ADMIN


def organizations_for_user(user):
    """Return only the organizations the current user is allowed to see."""
    if not user.is_authenticated:
        return Organization.objects.none()
    if is_admin(user):
        return Organization.objects.all()

    return get_user_organizations(user)


def projects_for_user(user):
    """Scope project visibility to the user's organizations unless they are an admin."""
    if not user.is_authenticated:
        return Project.objects.none()
    if is_admin(user):
        return Project.objects.all()

    organization_ids = organizations_for_user(user).values_list("pk", flat=True)
    return Project.objects.filter(organization_id__in=organization_ids)


def tasks_for_user(user):
    """Apply task visibility rules based on role.

    Admins can see everything, managers can see tasks inside their organizations,
    and members can only see work assigned directly to them.
    """
    if not user.is_authenticated:
        return Task.objects.none()
    role = get_user_role(user)
    if role == ROLE_ADMIN:
        return Task.objects.all()
    if role == ROLE_MANAGER:
        organization_ids = organizations_for_user(user).values_list("pk", flat=True)
        return Task.objects.filter(project__organization_id__in=organization_ids)
    return Task.objects.filter(assigned_to=user)


def manageable_users_for_user(user):
    """Return the user choices a manager/admin is allowed to assign work to."""
    if not user.is_authenticated:
        return User.objects.none()
    if is_admin(user):
        return User.objects.all().order_by("username")

    organization_ids = organizations_for_user(user).values_list("pk", flat=True)
    if not organization_ids:
        return User.objects.none()

    return User.objects.filter(profile__organizations__in=organization_ids).distinct().order_by("username")
