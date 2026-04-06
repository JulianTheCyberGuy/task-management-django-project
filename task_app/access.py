from django.contrib.auth import get_user_model

from .models import Organization, Project, Task


ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_MEMBER = "MEMBER"
MANAGE_ROLES = {ROLE_ADMIN, ROLE_MANAGER}


User = get_user_model()


def get_user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROLE_ADMIN

    profile = getattr(user, "profile", None)
    if profile and profile.role:
        return profile.role
    return ROLE_MEMBER


def get_user_organization(user):
    if not user.is_authenticated or user.is_superuser:
        return None
    profile = getattr(user, "profile", None)
    return getattr(profile, "organization", None)


def can_manage_app(user):
    return get_user_role(user) in MANAGE_ROLES


def is_admin(user):
    return get_user_role(user) == ROLE_ADMIN


def organizations_for_user(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    if is_admin(user):
        return Organization.objects.all()

    organization = get_user_organization(user)
    if organization is None:
        return Organization.objects.none()
    return Organization.objects.filter(pk=organization.pk)


def projects_for_user(user):
    if not user.is_authenticated:
        return Project.objects.none()
    if is_admin(user):
        return Project.objects.all()

    organization = get_user_organization(user)
    if organization is None:
        return Project.objects.none()
    return Project.objects.filter(organization=organization)


def tasks_for_user(user):
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
    if not user.is_authenticated:
        return User.objects.none()
    if is_admin(user):
        return User.objects.all().order_by("username")

    organization = get_user_organization(user)
    if organization is None:
        return User.objects.none()

    return User.objects.filter(profile__organization=organization).order_by("username")