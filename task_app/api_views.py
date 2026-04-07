"""Read-only API views for projects, tasks, calendar events, and audit logs.

The API intentionally reuses the same queryset scoping helpers as the HTML
views, which keeps permission boundaries consistent across the whole app.
"""

from calendar import monthrange
from datetime import date

from django.db.models import Count, Q
from django.utils.dateparse import parse_date
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from .access import projects_for_user, tasks_for_user
from .api_permissions import IsAdminApiUser
from .api_serializers import (
    AuditLogSerializer,
    CalendarTaskEventSerializer,
    ProjectDetailSerializer,
    ProjectSummarySerializer,
    TaskDetailSerializer,
    TaskListSerializer,
)
from .models import AuditLog


class StandardResultsSetPagination(PageNumberPagination):
    """Shared pagination so list endpoints behave consistently."""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ScopedProjectListApiView(generics.ListAPIView):
    """Return only the projects the current user is allowed to view."""
    serializer_class = ProjectSummarySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = projects_for_user(self.request.user).select_related("organization")
        active_value = self.request.query_params.get("active")
        organization_id = self.request.query_params.get("organization")
        query = self.request.query_params.get("q", "").strip()

        if active_value == "true":
            queryset = queryset.filter(is_active=True)
        elif active_value == "false":
            queryset = queryset.filter(is_active=False)

        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(organization__name__icontains=query)
            )

        return queryset.order_by("name")


class ScopedProjectDetailApiView(generics.RetrieveAPIView):
    """Return one in-scope project with summary counts included."""
    serializer_class = ProjectDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return projects_for_user(self.request.user).select_related("organization").annotate(
            task_total=Count("tasks", distinct=True),
            completed_task_total=Count("tasks", filter=Q(tasks__is_completed=True), distinct=True),
        )


class ScopedTaskListApiView(generics.ListAPIView):
    """Return a filterable list of in-scope tasks."""
    serializer_class = TaskListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = tasks_for_user(self.request.user).select_related("project__organization", "status", "assigned_to")
        completed_value = self.request.query_params.get("completed")
        project_id = self.request.query_params.get("project")
        status_id = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        due_before = parse_date(self.request.query_params.get("due_before", ""))
        due_after = parse_date(self.request.query_params.get("due_after", ""))
        query = self.request.query_params.get("q", "").strip()

        if completed_value == "true":
            queryset = queryset.filter(is_completed=True)
        elif completed_value == "false":
            queryset = queryset.filter(is_completed=False)

        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status_id:
            queryset = queryset.filter(status_id=status_id)
        if priority:
            queryset = queryset.filter(priority=priority)
        if due_after:
            queryset = queryset.filter(due_date__gte=due_after)
        if due_before:
            queryset = queryset.filter(due_date__lte=due_before)

        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(project__name__icontains=query)
                | Q(status__name__icontains=query)
            )

        return queryset.order_by("due_date", "title")


class ScopedTaskDetailApiView(generics.RetrieveAPIView):
    """Return one task only if it falls inside the user's allowed scope."""
    serializer_class = TaskDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return tasks_for_user(self.request.user).select_related("project__organization", "status", "assigned_to")


class CalendarEventListApiView(generics.ListAPIView):
    """Expose due-dated tasks as calendar-friendly event objects."""
    serializer_class = CalendarTaskEventSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def _get_date_range(self):
        start_param = self.request.query_params.get("start")
        end_param = self.request.query_params.get("end")
        today = date.today()

        if start_param or end_param:
            start_date = parse_date(start_param or "")
            end_date = parse_date(end_param or "")
            if not start_date or not end_date:
                raise ValidationError({"detail": "start and end must both be valid YYYY-MM-DD dates."})
            if end_date < start_date:
                raise ValidationError({"detail": "end date cannot be earlier than start date."})
            return start_date, end_date

        month_value = self.request.query_params.get("month")
        year_value = self.request.query_params.get("year")

        # Falling back to the current month makes the endpoint useful without any query params.
        if month_value is None and year_value is None:
            first_day = today.replace(day=1)
            last_day = today.replace(day=monthrange(today.year, today.month)[1])
            return first_day, last_day

        try:
            year_number = int(year_value or today.year)
            month_number = int(month_value or today.month)
            if month_number < 1 or month_number > 12:
                raise ValueError
        except ValueError as exc:
            raise ValidationError({"detail": "month must be 1-12 and year must be numeric."}) from exc

        first_day = date(year_number, month_number, 1)
        last_day = date(year_number, month_number, monthrange(year_number, month_number)[1])
        return first_day, last_day

    def get_queryset(self):
        start_date, end_date = self._get_date_range()
        queryset = tasks_for_user(self.request.user).select_related("project", "status", "assigned_to")
        queryset = queryset.filter(due_date__isnull=False, due_date__gte=start_date, due_date__lte=end_date)

        project_id = self.request.query_params.get("project")
        include_completed = self.request.query_params.get("include_completed", "true")

        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if include_completed == "false":
            queryset = queryset.filter(is_completed=False)

        return queryset.order_by("due_date", "priority", "title")


class AuditLogListApiView(generics.ListAPIView):
    """Administrator-only audit log listing endpoint."""
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminApiUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user")
        action = self.request.query_params.get("action")
        entity_type = self.request.query_params.get("entity_type")
        username = self.request.query_params.get("username")

        if action:
            queryset = queryset.filter(action=action)
        if entity_type:
            queryset = queryset.filter(entity_type__iexact=entity_type)
        if username:
            queryset = queryset.filter(user__username__icontains=username)

        return queryset.order_by("-created_at")


class AuditLogDetailApiView(generics.RetrieveAPIView):
    """Administrator-only detail endpoint for a single audit record."""
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminApiUser]
    queryset = AuditLog.objects.select_related("user").order_by("-created_at")
