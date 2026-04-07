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


def get_user_organization(user):
    """Return the user's scoped organization, if one exists."""
    if not user.is_authenticated or user.is_superuser:
        return None
    profile = getattr(user, "profile", None)
    return getattr(profile, "organization", None)


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

    organization = get_user_organization(user)
    if organization is None:
        return Organization.objects.none()
    return Organization.objects.filter(pk=organization.pk)


def projects_for_user(user):
    """Scope project visibility to the user's organization unless they are an admin."""
    if not user.is_authenticated:
        return Project.objects.none()
    if is_admin(user):
        return Project.objects.all()

    organization = get_user_organization(user)
    if organization is None:
        return Project.objects.none()
    return Project.objects.filter(organization=organization)


def tasks_for_user(user):
    """Apply task visibility rules based on role.

    Admins can see everything, managers can see tasks inside their organization,
    and members can only see work assigned directly to them.
    """
    if not user.is_authenticated:
        return Task.objects.none()
    role = get_user_role(user)
    if role == ROLE_ADMIN:
        return Task.objects.all()
    if role == ROLE_MANAGER:
        organization = get_user_organization(user)
        if organization is None:
            return Task.objects.none()
        return Task.objects.filter(project__organization=organization)
    return Task.objects.filter(assigned_to=user)


def manageable_users_for_user(user):
    """Return the user choices a manager/admin is allowed to assign work to."""
    if not user.is_authenticated:
        return User.objects.none()
    if is_admin(user):
        return User.objects.all().order_by("username")

    organization = get_user_organization(user)
    if organization is None:
        return User.objects.none()

    return User.objects.filter(profile__organization=organization).order_by("username")
