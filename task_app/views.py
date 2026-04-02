from django.urls import reverse_lazy
from django.views.generic import TemplateView, ListView, DetailView, CreateView, UpdateView

from .models import Organization, Project, TaskStatus, Task


class HomePageView(TemplateView):
    template_name = "task_app/home.html"


class OrganizationListView(ListView):
    model = Organization
    template_name = "task_app/organization_list.html"
    context_object_name = "organizations"


class OrganizationDetailView(DetailView):
    model = Organization
    template_name = "task_app/organization_detail.html"
    context_object_name = "organization"


class OrganizationCreateView(CreateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    fields = ["name", "contact_email", "phone_number"]
    success_url = reverse_lazy("organization-list")


class OrganizationUpdateView(UpdateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    fields = ["name", "contact_email", "phone_number"]
    success_url = reverse_lazy("organization-list")


class ProjectListView(ListView):
    model = Project
    template_name = "task_app/project_list.html"
    context_object_name = "projects"


class ProjectDetailView(DetailView):
    model = Project
    template_name = "task_app/project_detail.html"
    context_object_name = "project"


class ProjectCreateView(CreateView):
    model = Project
    template_name = "task_app/project_form.html"
    fields = ["organization", "name", "description", "start_date", "end_date", "is_active"]
    success_url = reverse_lazy("project-list")


class ProjectUpdateView(UpdateView):
    model = Project
    template_name = "task_app/project_form.html"
    fields = ["organization", "name", "description", "start_date", "end_date", "is_active"]
    success_url = reverse_lazy("project-list")


class TaskStatusListView(ListView):
    model = TaskStatus
    template_name = "task_app/taskstatus_list.html"
    context_object_name = "statuses"


class TaskStatusDetailView(DetailView):
    model = TaskStatus
    template_name = "task_app/taskstatus_detail.html"
    context_object_name = "status"


class TaskStatusCreateView(CreateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    fields = ["name", "description", "sort_order"]
    success_url = reverse_lazy("taskstatus-list")


class TaskStatusUpdateView(UpdateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    fields = ["name", "description", "sort_order"]
    success_url = reverse_lazy("taskstatus-list")


class TaskListView(ListView):
    model = Task
    template_name = "task_app/task_list.html"
    context_object_name = "tasks"


class TaskDetailView(DetailView):
    model = Task
    template_name = "task_app/task_detail.html"
    context_object_name = "task"


class TaskCreateView(CreateView):
    model = Task
    template_name = "task_app/task_form.html"
    fields = [
        "project",
        "status",
        "title",
        "description",
        "assigned_to",
        "due_date",
        "priority",
        "is_completed",
    ]
    success_url = reverse_lazy("task-list")


class TaskUpdateView(UpdateView):
    model = Task
    template_name = "task_app/task_form.html"
    fields = [
        "project",
        "status",
        "title",
        "description",
        "assigned_to",
        "due_date",
        "priority",
        "is_completed",
    ]
    success_url = reverse_lazy("task-list")