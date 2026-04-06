from pathlib import Path
import base64
import random

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from .models import Organization, Project, Task, TaskStatus


# Dashboard and summary views
class HomePageView(TemplateView):
    template_name = "task_app/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organization_count"] = Organization.objects.count()
        context["project_count"] = Project.objects.count()
        context["status_count"] = TaskStatus.objects.count()
        context["task_count"] = Task.objects.count()
        context["completed_task_count"] = Task.objects.filter(is_completed=True).count()
        context["incomplete_task_count"] = Task.objects.filter(is_completed=False).count()
        context["recent_tasks"] = Task.objects.select_related("project", "status").order_by("-id")[:5]
        context["status_summary"] = (
            TaskStatus.objects
            .annotate(task_total=Count("tasks"))
            .order_by("sort_order", "name")
        )
        return context


# Organization views
class OrganizationListView(ListView):
    model = Organization
    template_name = "task_app/organization_list.html"
    context_object_name = "organizations"
    queryset = Organization.objects.order_by("name")


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


# Project views
class ProjectListView(ListView):
    model = Project
    template_name = "task_app/project_list.html"
    context_object_name = "projects"
    queryset = Project.objects.select_related("organization").order_by("name")


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


# Task status views
class TaskStatusListView(ListView):
    model = TaskStatus
    template_name = "task_app/taskstatus_list.html"
    context_object_name = "statuses"
    queryset = TaskStatus.objects.order_by("sort_order", "name")


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


# Task views
class TaskListView(ListView):
    model = Task
    template_name = "task_app/task_list.html"
    context_object_name = "tasks"
    queryset = Task.objects.select_related("project", "status").order_by(
        "status__sort_order",
        "due_date",
        "title"
    )


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


# Secure access flow using RSA signature verification and short-lived session code
def secure_access_view(request):
    challenge_message = "unlock-task-report"

    if request.method == "POST":
        signature_b64 = request.POST.get("signature", "").strip()

        try:
            public_key_path = Path(__file__).resolve().parent / "keys" / "public_key.pem"
            public_key_data = public_key_path.read_bytes()
            public_key = load_pem_public_key(public_key_data)
            signature = base64.b64decode(signature_b64)

            public_key.verify(
                signature,
                challenge_message.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )

            unlock_code = f"{random.randint(0, 999999):06d}"
            request.session["secure_unlock_code"] = unlock_code
            request.session["secure_unlock_verified"] = False
            request.session["secure_unlock_created"] = timezone.now().isoformat()

            messages.success(
                request,
                "RSA signature verified successfully. A six-digit unlock code has been generated."
            )
            return redirect("secure-code")

        except Exception:
            messages.error(request, "Signature verification failed. Access denied.")

    return render(
        request,
        "task_app/secure_access.html",
        {
            "challenge_message": challenge_message,
        },
    )


def secure_code_view(request):
    unlock_code = request.session.get("secure_unlock_code")
    created_at_str = request.session.get("secure_unlock_created")

    if not unlock_code or not created_at_str:
        messages.error(request, "No verified unlock request was found. Please verify the RSA signature first.")
        return redirect("secure-access")

    created_at = timezone.datetime.fromisoformat(created_at_str)

    if timezone.is_naive(created_at):
        created_at = timezone.make_aware(created_at, timezone.get_current_timezone())

    if timezone.now() > created_at + timezone.timedelta(minutes=5):
        request.session.pop("secure_unlock_code", None)
        request.session.pop("secure_unlock_created", None)
        request.session.pop("secure_unlock_verified", None)

        messages.error(request, "Your six-digit unlock code expired. Please verify the signature again.")
        return redirect("secure-access")

    if request.method == "POST":
        entered_code = request.POST.get("unlock_code", "").strip()

        if entered_code == unlock_code:
            request.session["secure_unlock_verified"] = True
            messages.success(request, "Six-digit code verified successfully. Protected report unlocked.")
            return redirect("protected-report")

        messages.error(request, "Invalid six-digit code. Please try again.")

    return render(
        request,
        "task_app/secure_code.html",
        {
            "generated_code": unlock_code,
        },
    )


def protected_report_view(request):
    if not request.session.get("secure_unlock_verified"):
        messages.error(request, "You must complete secure verification before accessing this page.")
        return redirect("secure-access")

    tasks = Task.objects.select_related("project", "status").order_by("status__sort_order", "title")

    return render(
        request,
        "task_app/protected_report.html",
        {
            "tasks": tasks,
        },
    )