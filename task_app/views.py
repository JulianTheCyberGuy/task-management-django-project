import base64
import binascii
import csv
import secrets
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models.deletion import ProtectedError
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import urlencode
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView

from .access import (
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_MEMBER,
    can_manage_app,
    get_user_organization,
    get_user_role,
    is_admin,
    organizations_for_user,
    projects_for_user,
    tasks_for_user,
)
from .forms import AdminUserManagementForm, OrganizationForm, ProfileUpdateForm, ProjectForm, SignUpForm, TaskForm, TaskStatusForm
from .models import AuditLog, Organization, Project, SecurityEvent, Task, TaskStatus, UserProfile




User = get_user_model()

SORT_LABELS = {
    "name": "Name",
    "recent": "Recently Updated",
    "start": "Start Date",
    "end": "End Date",
    "due": "Due Date",
    "priority": "Priority",
    "status": "Status",
    "title": "Title",
}


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def write_audit_log(user, action, entity_type, summary, entity_id="", metadata=None):
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else "",
        summary=summary,
        metadata=metadata or {},
    )


def write_security_event(request, event_type, severity, details):
    SecurityEvent.objects.create(
        user=request.user if request.user.is_authenticated else None,
        event_type=event_type,
        severity=severity,
        ip_address=get_client_ip(request),
        details=details,
    )


def get_clean_query(request, key="q"):
    return request.GET.get(key, "").strip()


def apply_text_search(queryset, query, fields):
    if not query:
        return queryset
    search_filter = Q()
    for field in fields:
        search_filter |= Q(**{f"{field}__icontains": query})
    return queryset.filter(search_filter)



def _project_filtered_queryset(request):
    queryset = projects_for_user(request.user).select_related("organization").annotate(task_total=Count("tasks", distinct=True))
    query = get_clean_query(request)
    active_filter = request.GET.get("active", "all")
    sort_value = request.GET.get("sort", "name")

    queryset = apply_text_search(queryset, query, ["name", "description", "organization__name"])

    if active_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif active_filter == "inactive":
        queryset = queryset.filter(is_active=False)

    sort_map = {
        "name": ["name"],
        "recent": ["-created_at", "name"],
        "start": ["start_date", "name"],
        "end": ["end_date", "name"],
    }
    return queryset.order_by(*sort_map.get(sort_value, ["name"]))


def _task_filtered_queryset(request):
    queryset = tasks_for_user(request.user).select_related("project", "project__organization", "status", "assigned_to")
    query = get_clean_query(request)
    status_filter = request.GET.get("status", "all")
    priority_filter = request.GET.get("priority", "all")
    completion_filter = request.GET.get("completion", "all")
    due_filter = request.GET.get("due", "all")
    sort_value = request.GET.get("sort", "status")
    today = timezone.localdate()
    upcoming_window = today + timedelta(days=7)

    queryset = apply_text_search(
        queryset,
        query,
        ["title", "description", "project__name", "status__name", "assigned_to__username"],
    )

    if status_filter != "all":
        queryset = queryset.filter(status__pk=status_filter)
    if priority_filter != "all":
        queryset = queryset.filter(priority=priority_filter)
    if completion_filter == "open":
        queryset = queryset.filter(is_completed=False)
    elif completion_filter == "completed":
        queryset = queryset.filter(is_completed=True)

    if due_filter == "overdue":
        queryset = queryset.filter(is_completed=False, due_date__lt=today)
    elif due_filter == "today":
        queryset = queryset.filter(due_date=today)
    elif due_filter == "upcoming":
        queryset = queryset.filter(is_completed=False, due_date__gt=today, due_date__lte=upcoming_window)
    elif due_filter == "unscheduled":
        queryset = queryset.filter(due_date__isnull=True)

    sort_map = {
        "status": ["status__sort_order", "due_date", "title"],
        "due": ["due_date", "title"],
        "priority": ["-priority", "due_date", "title"],
        "recent": ["-updated_at", "title"],
        "title": ["title"],
    }
    return queryset.order_by(*sort_map.get(sort_value, ["status__sort_order", "due_date", "title"]))


def _build_csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response

def get_recent_window_days(request, default="30"):
    value = request.GET.get("window", default)
    if value not in {"7", "30", "90", "all"}:
        return default
    return value


def apply_recent_window(queryset, field_name, window_value):
    if window_value == "all":
        return queryset
    return queryset.filter(**{f"{field_name}__gte": timezone.now() - timedelta(days=int(window_value))})


def is_protected_resource_event(event_type):
    return event_type.startswith("protected_") or event_type.startswith("signature_")


def role_display_name(role_value):
    role_map = {
        ROLE_ADMIN: "Administrator",
        ROLE_MANAGER: "Manager",
        "MEMBER": "Member",
        None: "User",
    }
    return role_map.get(role_value, str(role_value).replace("_", " ").title())


def redirect_access_denied(request, minimum_role, message=None):
    role_name = role_display_name(minimum_role)
    denied_message = message or f"{role_name} access is required to access this page."
    target_url = reverse("access-denied")
    query_string = urlencode({"required_role": minimum_role, "message": denied_message})
    return redirect(f"{target_url}?{query_string}")


def access_denied_view(request):
    required_role = request.GET.get("required_role", "")
    context = {
        "required_role": role_display_name(required_role),
        "access_denied_message": request.GET.get("message") or "You do not have access to this page.",
    }
    return render(request, "task_app/access_denied.html", context, status=403)


def admin_portal_redirect_view(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    if not is_admin(request.user):
        write_security_event(request, "admin_access_denied", SecurityEvent.SEVERITY_WARNING, "User lacked administrator access for the admin portal.")
        return redirect_access_denied(request, ROLE_ADMIN, "Administrator access is required to access the admin portal.")
    return redirect("/admin/")


def verify_signature_against_challenge(public_key, signature, submitted_challenge):
    challenge_candidates = [submitted_challenge]
    for suffix in ["\n", "\r\n"]:
        candidate = f"{submitted_challenge}{suffix}"
        if candidate not in challenge_candidates:
            challenge_candidates.append(candidate)

    for candidate in challenge_candidates:
        try:
            public_key.verify(
                signature,
                candidate.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return candidate
        except InvalidSignature:
            continue

    raise InvalidSignature


def parse_session_iso_datetime(value):
    parsed_value = timezone.datetime.fromisoformat(value)
    if timezone.is_naive(parsed_value):
        parsed_value = timezone.make_aware(parsed_value, timezone.get_current_timezone())
    return parsed_value


class ScopedAccessMixin(LoginRequiredMixin):
    def get_user_role(self):
        return get_user_role(self.request.user)

    def get_user_organization(self):
        return get_user_organization(self.request.user)


class RoleRequiredMixin(ScopedAccessMixin, UserPassesTestMixin):
    permission_denied_message = "You do not have permission to access this resource."
    denied_event_type = "access_denied"
    minimum_role = ROLE_MEMBER

    def has_required_role(self):
        raise NotImplementedError("Subclasses must implement has_required_role().")

    def test_func(self):
        return self.has_required_role()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        write_security_event(
            self.request,
            self.denied_event_type,
            SecurityEvent.SEVERITY_WARNING,
            self.permission_denied_message,
        )
        context = {
            "required_role": role_display_name(self.minimum_role),
            "access_denied_message": self.permission_denied_message,
        }
        return render(self.request, "task_app/access_denied.html", context, status=403)


class ManagerRequiredMixin(RoleRequiredMixin):
    permission_denied_message = "Manager access is required to manage this resource."
    denied_event_type = "manager_access_denied"
    minimum_role = ROLE_MANAGER

    def has_required_role(self):
        return can_manage_app(self.request.user)


class AdminRequiredMixin(RoleRequiredMixin):
    permission_denied_message = "Administrator access is required to access this page."
    denied_event_type = "admin_access_denied"
    minimum_role = ROLE_ADMIN

    def has_required_role(self):
        return is_admin(self.request.user)


class UserScopedFormKwargsMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class AuditFormSuccessMixin:
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "object"

    def form_valid(self, form):
        response = super().form_valid(form)
        write_audit_log(
            user=self.request.user,
            action=self.audit_action,
            entity_type=self.audit_entity_type,
            entity_id=self.object.pk,
            summary=f"{self.audit_entity_type} {self.audit_action.lower()} completed",
            metadata={"path": self.request.path},
        )
        return response




class SafeDeleteMixin:
    template_name = "task_app/delete_confirm.html"
    success_url = reverse_lazy("home")
    audit_action = AuditLog.ACTION_DENIED
    audit_entity_type = "object"
    success_message = "Item deleted successfully."
    protected_error_message = "This item cannot be deleted because other records still depend on it."
    object_label_field = "name"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("object_label", getattr(self.object, self.object_label_field, str(self.object)))
        context.setdefault("entity_label", self.audit_entity_type.replace("_", " ").title())
        context.setdefault("cancel_url", self.get_cancel_url())
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        object_label = getattr(self.object, self.object_label_field, str(self.object))
        try:
            response = super().post(request, *args, **kwargs)
        except ProtectedError:
            messages.error(request, self.protected_error_message)
            write_audit_log(
                user=request.user,
                action=AuditLog.ACTION_DENIED,
                entity_type=self.audit_entity_type,
                entity_id=self.object.pk,
                summary=f"{self.audit_entity_type} delete blocked",
                metadata={"path": request.path},
            )
            return redirect(self.get_cancel_url())

        messages.success(request, self.success_message)
        write_audit_log(
            user=request.user,
            action=AuditLog.ACTION_UPDATE,
            entity_type=self.audit_entity_type,
            entity_id=self.object.pk,
            summary=f"{self.audit_entity_type} deleted",
            metadata={"path": request.path, "label": object_label},
        )
        return response

    def get_cancel_url(self):
        raise NotImplementedError("Subclasses must implement get_cancel_url().")

class SignUpView(CreateView):
    template_name = "registration/signup.html"
    form_class = SignUpForm
    success_url = reverse_lazy("home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object)
        messages.success(self.request, "Your account has been created successfully. Welcome to the task management app.")
        write_audit_log(
            user=self.object,
            action=AuditLog.ACTION_CREATE,
            entity_type="user_account",
            entity_id=self.object.pk,
            summary="User account registered through signup flow",
            metadata={"path": self.request.path},
        )
        return response


class ProfileView(ScopedAccessMixin, TemplateView):
    template_name = "task_app/profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile_form"] = ProfileUpdateForm(
            user=self.request.user,
            initial={
                "first_name": self.request.user.first_name,
                "last_name": self.request.user.last_name,
                "email": self.request.user.email,
            },
        )
        return context


class ProfileUpdateView(ScopedAccessMixin, FormView):
    form_class = ProfileUpdateForm
    template_name = "task_app/profile.html"
    success_url = reverse_lazy("profile")


    def get_initial(self):
        return {
            "first_name": self.request.user.first_name,
            "last_name": self.request.user.last_name,
            "email": self.request.user.email,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile_form"] = kwargs.get("form", self.get_form())
        return context

    def form_valid(self, form):
        form.save()
        write_audit_log(
            user=self.request.user,
            action=AuditLog.ACTION_UPDATE,
            entity_type="user_profile",
            entity_id=self.request.user.pk,
            summary="User updated their account profile",
            metadata={"path": self.request.path},
        )
        messages.success(self.request, "Your account details were updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


class HomePageView(ScopedAccessMixin, TemplateView):
    template_name = "task_app/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        scoped_organizations = organizations_for_user(user)
        scoped_projects = projects_for_user(user)
        scoped_tasks = tasks_for_user(user)
        today = timezone.localdate()
        upcoming_window = today + timedelta(days=7)

        incomplete_tasks = scoped_tasks.filter(is_completed=False)

        context["organization_count"] = scoped_organizations.count()
        context["project_count"] = scoped_projects.count()
        context["status_count"] = TaskStatus.objects.count()
        context["task_count"] = scoped_tasks.count()
        context["completed_task_count"] = scoped_tasks.filter(is_completed=True).count()
        context["incomplete_task_count"] = incomplete_tasks.count()
        context["active_project_count"] = scoped_projects.filter(is_active=True).count()
        context["overdue_task_count"] = incomplete_tasks.filter(due_date__lt=today).count()
        context["due_today_task_count"] = incomplete_tasks.filter(due_date=today).count()
        context["due_soon_task_count"] = incomplete_tasks.filter(due_date__gt=today, due_date__lte=upcoming_window).count()
        context["high_priority_open_task_count"] = incomplete_tasks.filter(priority=Task.PRIORITY_HIGH).count()
        context["recent_tasks"] = scoped_tasks.select_related("project", "status").order_by("-updated_at")[:5]
        context["overdue_tasks"] = incomplete_tasks.select_related("project", "status").filter(due_date__lt=today).order_by("due_date", "title")[:5]
        context["due_soon_tasks"] = incomplete_tasks.select_related("project", "status").filter(
            due_date__gte=today,
            due_date__lte=upcoming_window,
        ).order_by("due_date", "title")[:5]
        context["status_summary"] = (
            TaskStatus.objects.annotate(
                task_total=Count("tasks", filter=Q(tasks__in=scoped_tasks))
            ).order_by("sort_order", "name")
        )
        context["user_role"] = get_user_role(user)
        context["user_organization"] = get_user_organization(user)
        context["security_event_count"] = SecurityEvent.objects.count() if is_admin(user) else 0
        return context


class OrganizationListView(ScopedAccessMixin, ListView):
    model = Organization
    template_name = "task_app/organization_list.html"
    context_object_name = "organizations"

    def get_queryset(self):
        queryset = organizations_for_user(self.request.user).annotate(project_total=Count("projects", distinct=True))
        query = get_clean_query(self.request)
        queryset = apply_text_search(queryset, query, ["name", "contact_email", "phone_number"])
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = get_clean_query(self.request)
        context["result_count"] = context["organizations"].count()
        return context


class OrganizationDetailView(ScopedAccessMixin, DetailView):
    model = Organization
    template_name = "task_app/organization_detail.html"
    context_object_name = "organization"

    def get_queryset(self):
        return organizations_for_user(self.request.user)


class OrganizationCreateView(AdminRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, CreateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    form_class = OrganizationForm
    success_url = reverse_lazy("organization-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "organization"



class OrganizationUpdateView(AdminRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, UpdateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    form_class = OrganizationForm
    success_url = reverse_lazy("organization-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "organization"

    def get_queryset(self):
        return organizations_for_user(self.request.user)


class OrganizationDeleteView(AdminRequiredMixin, SafeDeleteMixin, DeleteView):
    model = Organization
    success_url = reverse_lazy("organization-list")
    audit_entity_type = "organization"
    success_message = "Organization deleted successfully."
    protected_error_message = "This organization cannot be deleted because it still has related records."

    def get_queryset(self):
        return organizations_for_user(self.request.user)

    def get_cancel_url(self):
        return reverse("organization-detail", args=[self.object.pk])


class ProjectListView(ScopedAccessMixin, ListView):
    model = Project
    template_name = "task_app/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        return _project_filtered_queryset(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = get_clean_query(self.request)
        context["active_filter"] = self.request.GET.get("active", "all")
        context["sort_value"] = self.request.GET.get("sort", "name")
        context["result_count"] = context["projects"].count()
        context["sort_options"] = [
            ("name", SORT_LABELS["name"]),
            ("recent", SORT_LABELS["recent"]),
            ("start", SORT_LABELS["start"]),
            ("end", SORT_LABELS["end"]),
        ]
        return context


class ProjectDetailView(ScopedAccessMixin, DetailView):
    model = Project
    template_name = "task_app/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        return projects_for_user(self.request.user).select_related("organization")


class ProjectCreateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, CreateView):
    model = Project
    template_name = "task_app/project_form.html"
    form_class = ProjectForm
    success_url = reverse_lazy("project-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "project"



class ProjectUpdateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, UpdateView):
    model = Project
    template_name = "task_app/project_form.html"
    form_class = ProjectForm
    success_url = reverse_lazy("project-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "project"

    def get_queryset(self):
        return projects_for_user(self.request.user)


class ProjectDeleteView(ManagerRequiredMixin, SafeDeleteMixin, DeleteView):
    model = Project
    success_url = reverse_lazy("project-list")
    audit_entity_type = "project"
    success_message = "Project deleted successfully."
    protected_error_message = "This project cannot be deleted right now because related records still depend on it."

    def get_queryset(self):
        return projects_for_user(self.request.user)

    def get_cancel_url(self):
        return reverse("project-detail", args=[self.object.pk])


class TaskStatusListView(ScopedAccessMixin, ListView):
    model = TaskStatus
    template_name = "task_app/taskstatus_list.html"
    context_object_name = "statuses"

    def get_queryset(self):
        queryset = TaskStatus.objects.annotate(task_total=Count("tasks", distinct=True))
        query = get_clean_query(self.request)
        queryset = apply_text_search(queryset, query, ["name", "description"])
        return queryset.order_by("sort_order", "name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = get_clean_query(self.request)
        context["result_count"] = context["statuses"].count()
        return context


class TaskStatusDetailView(ScopedAccessMixin, DetailView):
    model = TaskStatus
    template_name = "task_app/taskstatus_detail.html"
    context_object_name = "status"


class TaskStatusCreateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, CreateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    form_class = TaskStatusForm
    success_url = reverse_lazy("taskstatus-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "task_status"



class TaskStatusUpdateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, UpdateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    form_class = TaskStatusForm
    success_url = reverse_lazy("taskstatus-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "task_status"


class TaskStatusDeleteView(ManagerRequiredMixin, SafeDeleteMixin, DeleteView):
    model = TaskStatus
    success_url = reverse_lazy("taskstatus-list")
    audit_entity_type = "task_status"
    success_message = "Task status deleted successfully."
    protected_error_message = "This task status cannot be deleted because tasks are still using it."

    def get_cancel_url(self):
        return reverse("taskstatus-detail", args=[self.object.pk])


class TaskListView(ScopedAccessMixin, ListView):
    model = Task
    template_name = "task_app/task_list.html"
    context_object_name = "tasks"

    def get_queryset(self):
        return _task_filtered_queryset(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scoped_tasks = tasks_for_user(self.request.user)
        today = timezone.localdate()
        upcoming_window = today + timedelta(days=7)

        context["search_query"] = get_clean_query(self.request)
        context["status_filter"] = self.request.GET.get("status", "all")
        context["priority_filter"] = self.request.GET.get("priority", "all")
        context["completion_filter"] = self.request.GET.get("completion", "all")
        context["due_filter"] = self.request.GET.get("due", "all")
        context["sort_value"] = self.request.GET.get("sort", "status")
        context["available_statuses"] = TaskStatus.objects.order_by("sort_order", "name")
        context["result_count"] = context["tasks"].count()
        context["task_open_count"] = scoped_tasks.filter(is_completed=False).count()
        context["task_overdue_count"] = scoped_tasks.filter(is_completed=False, due_date__lt=today).count()
        context["task_due_soon_count"] = scoped_tasks.filter(
            is_completed=False,
            due_date__gt=today,
            due_date__lte=upcoming_window,
        ).count()
        context["task_completed_count"] = scoped_tasks.filter(is_completed=True).count()
        context["sort_options"] = [
            ("status", SORT_LABELS["status"]),
            ("due", SORT_LABELS["due"]),
            ("priority", SORT_LABELS["priority"]),
            ("recent", SORT_LABELS["recent"]),
            ("title", SORT_LABELS["title"]),
        ]
        return context


class TaskDetailView(ScopedAccessMixin, DetailView):
    model = Task
    template_name = "task_app/task_detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return tasks_for_user(self.request.user).select_related("project", "status", "assigned_to")


class TaskDeleteView(ManagerRequiredMixin, SafeDeleteMixin, DeleteView):
    model = Task
    success_url = reverse_lazy("task-list")
    audit_entity_type = "task"
    success_message = "Task deleted successfully."
    object_label_field = "title"

    def get_queryset(self):
        return tasks_for_user(self.request.user)

    def get_cancel_url(self):
        return reverse("task-detail", args=[self.object.pk])


class TaskCreateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, CreateView):
    model = Task
    template_name = "task_app/task_form.html"
    form_class = TaskForm
    success_url = reverse_lazy("task-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "task"



class TaskUpdateView(ManagerRequiredMixin, UserScopedFormKwargsMixin, AuditFormSuccessMixin, UpdateView):
    model = Task
    template_name = "task_app/task_form.html"
    form_class = TaskForm
    success_url = reverse_lazy("task-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "task"

    def get_queryset(self):
        return tasks_for_user(self.request.user)



class SecurityDashboardView(AdminRequiredMixin, TemplateView):
    template_name = "task_app/security_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        window_value = get_recent_window_days(self.request)
        audit_logs = apply_recent_window(AuditLog.objects.select_related("user"), "created_at", window_value)
        security_events = apply_recent_window(SecurityEvent.objects.select_related("user"), "created_at", window_value)

        denied_audit_logs = audit_logs.filter(action=AuditLog.ACTION_DENIED)
        warning_events = security_events.filter(severity=SecurityEvent.SEVERITY_WARNING)
        error_events = security_events.filter(severity=SecurityEvent.SEVERITY_ERROR)
        protected_events = security_events.filter(
            Q(event_type__startswith="protected_") | Q(event_type__startswith="signature_")
        )

        context.update({
            "window_value": window_value,
            "audit_total": audit_logs.count(),
            "security_event_total": security_events.count(),
            "denied_audit_total": denied_audit_logs.count(),
            "warning_event_total": warning_events.count(),
            "error_event_total": error_events.count(),
            "protected_event_total": protected_events.count(),
            "recent_audit_logs": audit_logs.order_by("-created_at")[:8],
            "recent_security_events": security_events.order_by("-created_at")[:8],
            "top_audit_actions": audit_logs.values("action").annotate(total=Count("id")).order_by("-total", "action")[:6],
            "top_event_types": security_events.values("event_type").annotate(total=Count("id")).order_by("-total", "event_type")[:6],
            "failed_access_types": security_events.filter(severity__in=[SecurityEvent.SEVERITY_WARNING, SecurityEvent.SEVERITY_ERROR]).values("event_type").annotate(total=Count("id")).order_by("-total", "event_type")[:6],
            "protected_access_days": protected_events.annotate(day=TruncDate("created_at")).values("day").annotate(total=Count("id")).order_by("-day")[:7],
        })
        return context


class AuditLogListView(AdminRequiredMixin, ListView):
    model = AuditLog
    template_name = "task_app/audit_log_list.html"
    context_object_name = "audit_logs"
    paginate_by = 25

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("user")
        query = get_clean_query(self.request)
        action_filter = self.request.GET.get("action", "all")
        entity_filter = self.request.GET.get("entity", "all")
        window_value = get_recent_window_days(self.request)

        queryset = apply_recent_window(queryset, "created_at", window_value)
        queryset = apply_text_search(queryset, query, ["summary", "entity_type", "entity_id", "user__username"])

        if action_filter != "all":
            queryset = queryset.filter(action=action_filter)
        if entity_filter != "all":
            queryset = queryset.filter(entity_type=entity_filter)

        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtered_queryset = self.get_queryset()
        context["search_query"] = get_clean_query(self.request)
        context["action_filter"] = self.request.GET.get("action", "all")
        context["entity_filter"] = self.request.GET.get("entity", "all")
        context["window_value"] = get_recent_window_days(self.request)
        context["result_count"] = filtered_queryset.count()
        context["action_options"] = AuditLog.ACTION_CHOICES
        context["entity_options"] = list(AuditLog.objects.order_by("entity_type").values_list("entity_type", flat=True).distinct())
        return context


class SecurityEventListView(AdminRequiredMixin, ListView):
    model = SecurityEvent
    template_name = "task_app/security_event_list.html"
    context_object_name = "security_events"
    paginate_by = 25

    def get_queryset(self):
        queryset = SecurityEvent.objects.select_related("user")
        query = get_clean_query(self.request)
        severity_filter = self.request.GET.get("severity", "all")
        event_type_filter = self.request.GET.get("event_type", "all")
        window_value = get_recent_window_days(self.request)

        queryset = apply_recent_window(queryset, "created_at", window_value)
        queryset = apply_text_search(queryset, query, ["event_type", "details", "user__username", "ip_address"])

        if severity_filter != "all":
            queryset = queryset.filter(severity=severity_filter)
        if event_type_filter != "all":
            queryset = queryset.filter(event_type=event_type_filter)

        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtered_queryset = self.get_queryset()
        context["search_query"] = get_clean_query(self.request)
        context["severity_filter"] = self.request.GET.get("severity", "all")
        context["event_type_filter"] = self.request.GET.get("event_type", "all")
        context["window_value"] = get_recent_window_days(self.request)
        context["result_count"] = filtered_queryset.count()
        context["severity_options"] = SecurityEvent.SEVERITY_CHOICES
        context["event_type_options"] = list(filtered_queryset.order_by("event_type").values_list("event_type", flat=True).distinct())
        return context


class FailedAccessView(AdminRequiredMixin, TemplateView):
    template_name = "task_app/failed_access_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        window_value = get_recent_window_days(self.request)
        denied_audit_logs = apply_recent_window(
            AuditLog.objects.select_related("user").filter(action=AuditLog.ACTION_DENIED),
            "created_at",
            window_value,
        ).order_by("-created_at")
        failed_events = apply_recent_window(
            SecurityEvent.objects.select_related("user").filter(severity__in=[SecurityEvent.SEVERITY_WARNING, SecurityEvent.SEVERITY_ERROR]),
            "created_at",
            window_value,
        ).order_by("-created_at")

        context.update({
            "window_value": window_value,
            "denied_audit_total": denied_audit_logs.count(),
            "failed_event_total": failed_events.count(),
            "denied_audit_logs": denied_audit_logs[:15],
            "failed_events": failed_events[:15],
            "failed_by_user": failed_events.values("user__username").annotate(total=Count("id")).order_by("-total", "user__username")[:8],
            "failed_by_ip": failed_events.exclude(ip_address__isnull=True).exclude(ip_address="").values("ip_address").annotate(total=Count("id")).order_by("-total", "ip_address")[:8],
            "failed_by_type": failed_events.values("event_type").annotate(total=Count("id")).order_by("-total", "event_type")[:8],
        })
        return context


class ProtectedAccessHistoryView(AdminRequiredMixin, TemplateView):
    template_name = "task_app/protected_access_history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        window_value = get_recent_window_days(self.request)
        protected_audits = apply_recent_window(
            AuditLog.objects.select_related("user").filter(entity_type="protected_report"),
            "created_at",
            window_value,
        ).order_by("-created_at")
        protected_events = apply_recent_window(
            SecurityEvent.objects.select_related("user").filter(
                Q(event_type__startswith="protected_") | Q(event_type__startswith="signature_")
            ),
            "created_at",
            window_value,
        ).order_by("-created_at")

        context.update({
            "window_value": window_value,
            "protected_view_total": protected_audits.filter(action=AuditLog.ACTION_VIEW).count(),
            "protected_verify_total": protected_audits.filter(action=AuditLog.ACTION_VERIFY).count(),
            "protected_denied_total": protected_audits.filter(action=AuditLog.ACTION_DENIED).count(),
            "protected_event_total": protected_events.count(),
            "protected_audits": protected_audits[:20],
            "protected_events": protected_events[:20],
        })
        return context




class OrganizationExportCsvView(ScopedAccessMixin, View):
    def get(self, request, *args, **kwargs):
        organizations = organizations_for_user(request.user).annotate(project_total=Count("projects", distinct=True))
        query = get_clean_query(request)
        organizations = apply_text_search(organizations, query, ["name", "contact_email", "phone_number"]).order_by("name")

        write_audit_log(
            user=request.user,
            action=AuditLog.ACTION_VIEW,
            entity_type="organization_export",
            summary="Exported organization list to CSV",
            metadata={"path": request.path, "query": query},
        )

        rows = [
            [
                organization.pk,
                organization.name,
                organization.contact_email,
                organization.phone_number,
                organization.project_total,
                organization.created_at.isoformat(),
            ]
            for organization in organizations
        ]
        return _build_csv_response(
            "organizations_export.csv",
            ["ID", "Name", "Contact Email", "Phone Number", "Project Count", "Created At"],
            rows,
        )


class ProjectExportCsvView(ScopedAccessMixin, View):
    def get(self, request, *args, **kwargs):
        projects = _project_filtered_queryset(request)

        write_audit_log(
            user=request.user,
            action=AuditLog.ACTION_VIEW,
            entity_type="project_export",
            summary="Exported project list to CSV",
            metadata={
                "path": request.path,
                "query": get_clean_query(request),
                "active": request.GET.get("active", "all"),
                "sort": request.GET.get("sort", "name"),
            },
        )

        rows = [
            [
                project.pk,
                project.name,
                project.organization.name,
                project.description,
                project.start_date.isoformat() if project.start_date else "",
                project.end_date.isoformat() if project.end_date else "",
                "Yes" if project.is_active else "No",
                project.task_total,
                project.created_at.isoformat(),
            ]
            for project in projects
        ]
        return _build_csv_response(
            "projects_export.csv",
            ["ID", "Name", "Organization", "Description", "Start Date", "End Date", "Active", "Task Count", "Created At"],
            rows,
        )


class TaskExportCsvView(ScopedAccessMixin, View):
    def get(self, request, *args, **kwargs):
        tasks = _task_filtered_queryset(request)

        write_audit_log(
            user=request.user,
            action=AuditLog.ACTION_VIEW,
            entity_type="task_export",
            summary="Exported task list to CSV",
            metadata={
                "path": request.path,
                "query": get_clean_query(request),
                "status": request.GET.get("status", "all"),
                "priority": request.GET.get("priority", "all"),
                "completion": request.GET.get("completion", "all"),
                "due": request.GET.get("due", "all"),
                "sort": request.GET.get("sort", "status"),
            },
        )

        rows = [
            [
                task.pk,
                task.title,
                task.project.name,
                task.project.organization.name,
                task.status.name,
                task.assigned_to.username if task.assigned_to else "",
                task.priority,
                "Yes" if task.is_completed else "No",
                task.due_date.isoformat() if task.due_date else "",
                task.updated_at.isoformat(),
            ]
            for task in tasks
        ]
        return _build_csv_response(
            "tasks_export.csv",
            ["ID", "Title", "Project", "Organization", "Status", "Assigned To", "Priority", "Completed", "Due Date", "Updated At"],
            rows,
        )


def issue_secure_challenge(request):
    challenge = secrets.token_urlsafe(32)
    issued_at = timezone.now().isoformat()
    request.session["secure_challenge"] = challenge
    request.session["secure_challenge_issued_at"] = issued_at
    request.session["secure_verified_at"] = None
    return challenge


def secure_access_view(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    if not can_manage_app(request.user):
        write_security_event(request, "protected_access_denied", SecurityEvent.SEVERITY_WARNING, "User lacks role for secure access page.")
        return redirect_access_denied(request, ROLE_MANAGER, "Manager access is required to use Secure Access.")

    current_challenge = request.session.get("secure_challenge") or issue_secure_challenge(request)
    issued_at = request.session.get("secure_challenge_issued_at")

    if request.method == "POST":
        signature_b64 = request.POST.get("signature", "").strip()
        submitted_challenge = request.session.get("secure_challenge")
        if not submitted_challenge or not issued_at:
            messages.error(request, "Your secure challenge expired. Please try again.")
            issue_secure_challenge(request)
            return redirect("secure-access")

        issued_at_dt = parse_session_iso_datetime(issued_at)
        if timezone.now() > issued_at_dt + timedelta(minutes=5):
            write_security_event(request, "signature_challenge_expired", SecurityEvent.SEVERITY_WARNING, "Secure challenge expired before signature verification.")
            messages.error(request, "Your secure challenge expired. Please sign the new challenge.")
            issue_secure_challenge(request)
            return redirect("secure-access")

        try:
            public_key_data = settings.SECURE_ACCESS_PUBLIC_KEY_PATH.read_bytes()
            public_key = load_pem_public_key(public_key_data)
            normalized_signature = "".join(signature_b64.split())
            signature = base64.b64decode(normalized_signature)
            verified_candidate = verify_signature_against_challenge(public_key, signature, submitted_challenge)
            request.session["secure_verified_at"] = timezone.now().isoformat()
            request.session.pop("secure_challenge", None)
            request.session.pop("secure_challenge_issued_at", None)
            write_audit_log(
                user=request.user,
                action=AuditLog.ACTION_VERIFY,
                entity_type="protected_report",
                summary="RSA challenge verified successfully",
                metadata={"path": request.path, "matched_variant": "exact" if verified_candidate == submitted_challenge else "normalized_newline_variant"},
            )
            write_security_event(request, "signature_verification_success", SecurityEvent.SEVERITY_INFO, "Protected report challenge verified successfully.")
            messages.success(request, "Signature verified successfully. Protected report access is temporarily unlocked.")
            return redirect("protected-report")
        except binascii.Error:
            write_security_event(request, "signature_format_invalid", SecurityEvent.SEVERITY_WARNING, "A malformed Base64 signature was submitted for secure access.")
            messages.error(request, "The submitted signature is not valid Base64. Paste the full signature exactly as generated.")
            current_challenge = issue_secure_challenge(request)
        except (ValueError, InvalidSignature):
            write_audit_log(
                user=request.user,
                action=AuditLog.ACTION_DENIED,
                entity_type="protected_report",
                summary="RSA challenge verification failed",
                metadata={"path": request.path},
            )
            write_security_event(request, "signature_verification_failed", SecurityEvent.SEVERITY_WARNING, "An invalid signature was submitted for the protected report challenge.")
            messages.error(request, "Signature verification failed. Please try again.")
            current_challenge = issue_secure_challenge(request)

    return render(request, "task_app/secure_access.html", {"challenge_message": current_challenge})


def protected_report_view(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    if not can_manage_app(request.user):
        write_security_event(request, "protected_report_denied", SecurityEvent.SEVERITY_WARNING, "User lacked role for protected report access.")
        return redirect_access_denied(request, ROLE_MANAGER, "Manager access is required to view the protected report.")

    verified_at_str = request.session.get("secure_verified_at")
    if not verified_at_str:
        messages.error(request, "You must verify a signed challenge before accessing this report.")
        return redirect("secure-access")

    verified_at = parse_session_iso_datetime(verified_at_str)
    if timezone.now() > verified_at + timedelta(minutes=10):
        request.session.pop("secure_verified_at", None)
        write_security_event(request, "protected_report_verification_expired", SecurityEvent.SEVERITY_WARNING, "Protected report access window expired.")
        messages.error(request, "Your protected report verification window expired. Please sign a new challenge.")
        return redirect("secure-access")

    tasks = tasks_for_user(request.user).select_related("project", "status", "assigned_to").order_by("status__sort_order", "title")
    write_audit_log(
        user=request.user,
        action=AuditLog.ACTION_VIEW,
        entity_type="protected_report",
        summary="Protected report viewed",
        metadata={"task_count": tasks.count()},
    )
    write_security_event(request, "protected_report_viewed", SecurityEvent.SEVERITY_INFO, f"Protected report viewed with {tasks.count()} tasks in scope.")
    return render(request, "task_app/protected_report.html", {"tasks": tasks})

class ManageUserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = "task_app/manage_user_list.html"
    context_object_name = "managed_users"

    def get_queryset(self):
        queryset = User.objects.select_related("profile", "profile__organization").annotate(
            assigned_task_total=Count("assigned_tasks", distinct=True)
        )
        query = get_clean_query(self.request)
        queryset = apply_text_search(
            queryset,
            query,
            ["username", "first_name", "last_name", "email", "profile__organization__name"],
        )
        return queryset.order_by("username")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = get_clean_query(self.request)
        context["result_count"] = context["managed_users"].count()
        return context


class ManageUserDetailView(AdminRequiredMixin, DetailView):
    model = User
    template_name = "task_app/manage_user_detail.html"
    context_object_name = "managed_user"

    def get_queryset(self):
        return User.objects.select_related("profile", "profile__organization")


class ManageUserUpdateView(AdminRequiredMixin, UpdateView):
    model = UserProfile
    form_class = AdminUserManagementForm
    template_name = "task_app/manage_user_form.html"

    def get_object(self, queryset=None):
        managed_user = User.objects.get(pk=self.kwargs["pk"])
        profile, _ = UserProfile.objects.get_or_create(user=managed_user)
        return profile

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["managed_user"] = self.object.user
        return context

    def form_valid(self, form):
        messages.success(self.request, "User access details updated successfully.")
        write_audit_log(
            user=self.request.user,
            action=AuditLog.ACTION_UPDATE,
            entity_type="user_profile",
            entity_id=self.object.user.pk,
            summary="Administrator updated a user role or organization assignment",
            metadata={"path": self.request.path},
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("manage-user-detail", kwargs={"pk": self.object.user.pk})
