"""URL routes for the read-only API layer."""

from django.urls import path

from .api_views import (
    AuditLogDetailApiView,
    AuditLogListApiView,
    CalendarEventListApiView,
    ScopedProjectDetailApiView,
    ScopedProjectListApiView,
    ScopedTaskDetailApiView,
    ScopedTaskListApiView,
)


urlpatterns = [
    path("projects/", ScopedProjectListApiView.as_view(), name="api-project-list"),
    path("projects/<int:pk>/", ScopedProjectDetailApiView.as_view(), name="api-project-detail"),
    path("tasks/", ScopedTaskListApiView.as_view(), name="api-task-list"),
    path("tasks/<int:pk>/", ScopedTaskDetailApiView.as_view(), name="api-task-detail"),
    path("calendar/events/", CalendarEventListApiView.as_view(), name="api-calendar-events"),
    # Audit endpoints are intentionally kept separate because they have stricter admin-only permissions.
    path("audit-logs/", AuditLogListApiView.as_view(), name="api-audit-log-list"),
    path("audit-logs/<int:pk>/", AuditLogDetailApiView.as_view(), name="api-audit-log-detail"),
]
