"""Core data models for the task management app.

The models in this file intentionally separate organizational ownership,
workflow status, operational tasks, and security/audit records. That keeps the
business entities clean while still supporting traceability for sensitive
actions.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


User = get_user_model()


class Organization(models.Model):
    """Top-level tenant-like grouping used to scope users, projects, and tasks."""
    name = models.CharField(max_length=150, unique=True)
    contact_email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """App-specific profile data kept separate from Django's built-in user model."""
    ROLE_ADMIN = "ADMIN"
    ROLE_MANAGER = "MANAGER"
    ROLE_MEMBER = "MEMBER"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_MEMBER, "Member"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} profile"


class Project(models.Model):
    """A project belongs to one organization and groups related task work."""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        # Project names only need to be unique inside the same organization.
        unique_together = ("organization", "name")

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


class TaskStatus(models.Model):
    """Reusable workflow status values such as Open, In Progress, or Complete."""
    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Task statuses"

    def __str__(self):
        return self.name


class Task(models.Model):
    """Primary work item model for the application."""
    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MED"
    PRIORITY_HIGH = "HIGH"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    status = models.ForeignKey(
        TaskStatus,
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(
        max_length=4,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM,
    )
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "title"]

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    """Business-action audit record used for accountability and reporting."""
    ACTION_CREATE = "CREATE"
    ACTION_UPDATE = "UPDATE"
    ACTION_VIEW = "VIEW"
    ACTION_VERIFY = "VERIFY"
    ACTION_DENIED = "DENIED"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_VIEW, "View"),
        (ACTION_VERIFY, "Verify"),
        (ACTION_DENIED, "Denied"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=50, blank=True)
    summary = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.entity_type}"


class SecurityEvent(models.Model):
    """Operational security record for denied access, challenge failures, and similar events."""
    SEVERITY_INFO = "INFO"
    SEVERITY_WARNING = "WARNING"
    SEVERITY_ERROR = "ERROR"
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, "Info"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_ERROR, "Error"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.severity})"


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    """Guarantee every user has a profile even if created outside the signup form."""
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # get_or_create protects the app from historical users created before the profile model existed.
        UserProfile.objects.get_or_create(user=instance)
