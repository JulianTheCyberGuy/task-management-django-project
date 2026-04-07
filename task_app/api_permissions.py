from rest_framework.permissions import BasePermission

from .access import is_admin


class IsAdminApiUser(BasePermission):
    message = "You must be an administrator to access this API endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and is_admin(request.user))
