"""Django admin registrations for all core app models."""

from django.contrib import admin

from .models import AuditLog, Organization, Project, SecurityEvent, Task, TaskStatus, UserProfile


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin configuration for organization records."""
    list_display = ("name", "contact_email", "phone_number", "created_at")
    search_fields = ("name", "contact_email", "phone_number")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Makes role and organization assignments manageable from the admin site."""
    list_display = ("user", "organization", "role", "updated_at")
    list_filter = ("role", "organization")
    search_fields = ("user__username", "user__email")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Project admin view focused on lifecycle and tenant ownership."""
    list_display = ("name", "organization", "is_active", "start_date", "end_date")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "organization__name")


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    """Keeps task workflow values easy to reorder and review."""
    list_display = ("name", "sort_order")
    ordering = ("sort_order", "name")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """Operational task admin screen with common filters for triage."""
    list_display = ("title", "project", "status", "priority", "assigned_to", "due_date", "is_completed")
    list_filter = ("status", "priority", "is_completed", "project__organization")
    search_fields = ("title", "project__name", "assigned_to__username")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Audit entries should be searchable but not manually backdated."""
    list_display = ("created_at", "user", "action", "entity_type", "entity_id", "summary")
    list_filter = ("action", "entity_type")
    search_fields = ("summary", "entity_type", "entity_id", "user__username")
    readonly_fields = ("created_at",)


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Surface security-relevant signals for operational review."""
    list_display = ("created_at", "user", "event_type", "severity", "ip_address")
    list_filter = ("severity", "event_type")
    search_fields = ("event_type", "details", "user__username", "ip_address")
    readonly_fields = ("created_at",)
