"""DRF serializers for the scoped task management API.

Most serializers expose human-readable convenience fields like project_name and
status_name so the frontend or API consumers do not need to make extra lookup
requests just to render labels.
"""

from rest_framework import serializers

from .models import AuditLog, Project, Task, TaskStatus


class TaskStatusSummarySerializer(serializers.ModelSerializer):
    """Compact task status payload used where full status objects are unnecessary."""
    class Meta:
        model = TaskStatus
        fields = ["id", "name", "description", "sort_order"]


class ProjectSummarySerializer(serializers.ModelSerializer):
    """List-focused project serializer with organization label included."""
    organization_name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "organization",
            "organization_name",
            "description",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
        ]


class ProjectDetailSerializer(serializers.ModelSerializer):
    """Project detail serializer that includes task summary counts."""
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    task_total = serializers.IntegerField(read_only=True)
    completed_task_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "organization",
            "organization_name",
            "description",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
            "task_total",
            "completed_task_total",
        ]


class TaskListSerializer(serializers.ModelSerializer):
    """Task serializer optimized for list screens and table-style output."""
    project_name = serializers.CharField(source="project.name", read_only=True)
    organization_name = serializers.CharField(source="project.organization.name", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "project",
            "project_name",
            "organization_name",
            "status",
            "status_name",
            "assigned_to",
            "assigned_to_username",
            "due_date",
            "priority",
            "is_completed",
            "created_at",
            "updated_at",
        ]


class TaskDetailSerializer(serializers.ModelSerializer):
    """Expanded task serializer that includes description and relational labels."""
    project_name = serializers.CharField(source="project.name", read_only=True)
    organization_name = serializers.CharField(source="project.organization.name", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "project",
            "project_name",
            "organization_name",
            "status",
            "status_name",
            "assigned_to",
            "assigned_to_username",
            "due_date",
            "priority",
            "is_completed",
            "created_at",
            "updated_at",
        ]


class CalendarTaskEventSerializer(serializers.ModelSerializer):
    """Serializer used by the calendar view so tasks can be treated like events."""
    project_name = serializers.CharField(source="project.name", read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True)
    assigned_to_username = serializers.CharField(source="assigned_to.username", read_only=True)
    event_date = serializers.DateField(source="due_date", read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "event_date",
            "project",
            "project_name",
            "status",
            "status_name",
            "assigned_to",
            "assigned_to_username",
            "priority",
            "is_completed",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    """Read-only serializer for audit entries exposed to administrators."""
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "username",
            "action",
            "entity_type",
            "entity_id",
            "summary",
            "metadata",
            "created_at",
        ]
