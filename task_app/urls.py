from django.urls import path
from .views import (
    HomePageView,
    OrganizationListView,
    OrganizationDetailView,
    OrganizationCreateView,
    OrganizationUpdateView,
    ProjectListView,
    ProjectDetailView,
    ProjectCreateView,
    ProjectUpdateView,
    TaskStatusListView,
    TaskStatusDetailView,
    TaskStatusCreateView,
    TaskStatusUpdateView,
    TaskListView,
    TaskDetailView,
    TaskCreateView,
    TaskUpdateView,
    secure_access_view,
    secure_code_view,
    protected_report_view,
)

urlpatterns = [
    path("", HomePageView.as_view(), name="home"),

    path("organizations/", OrganizationListView.as_view(), name="organization-list"),
    path("organizations/add/", OrganizationCreateView.as_view(), name="organization-add"),
    path("organizations/<int:pk>/", OrganizationDetailView.as_view(), name="organization-detail"),
    path("organizations/<int:pk>/edit/", OrganizationUpdateView.as_view(), name="organization-edit"),

    path("projects/", ProjectListView.as_view(), name="project-list"),
    path("projects/add/", ProjectCreateView.as_view(), name="project-add"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/edit/", ProjectUpdateView.as_view(), name="project-edit"),

    path("statuses/", TaskStatusListView.as_view(), name="taskstatus-list"),
    path("statuses/add/", TaskStatusCreateView.as_view(), name="taskstatus-add"),
    path("statuses/<int:pk>/", TaskStatusDetailView.as_view(), name="taskstatus-detail"),
    path("statuses/<int:pk>/edit/", TaskStatusUpdateView.as_view(), name="taskstatus-edit"),

    path("tasks/", TaskListView.as_view(), name="task-list"),
    path("tasks/add/", TaskCreateView.as_view(), name="task-add"),
    path("tasks/<int:pk>/", TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:pk>/edit/", TaskUpdateView.as_view(), name="task-edit"),

    path("secure-access/", secure_access_view, name="secure-access"),
    path("secure-code/", secure_code_view, name="secure-code"),
    path("protected-report/", protected_report_view, name="protected-report"),
]