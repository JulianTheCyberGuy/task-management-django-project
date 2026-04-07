import base64
import secrets
from datetime import timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from .access import (
    can_manage_app,
    get_user_organization,
    get_user_role,
    is_admin,
    organizations_for_user,
    projects_for_user,
    tasks_for_user,
)
from .forms import OrganizationForm, ProfileUpdateForm, ProjectForm, SignUpForm, TaskForm, TaskStatusForm
from .models import AuditLog, Organization, Project, SecurityEvent, Task, TaskStatus


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


class ScopedAccessMixin(LoginRequiredMixin):
    def get_user_role(self):
        return get_user_role(self.request.user)

    def get_user_organization(self):
        return get_user_organization(self.request.user)


class ManagerRequiredMixin(ScopedAccessMixin, UserPassesTestMixin):
    permission_denied_message = "You do not have permission to manage this resource."

    def test_func(self):
        return can_manage_app(self.request.user)


class AdminRequiredMixin(ScopedAccessMixin, UserPassesTestMixin):
    permission_denied_message = "You must be an administrator to access this page."

    def test_func(self):
        return is_admin(self.request.user)


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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

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


class OrganizationCreateView(AdminRequiredMixin, AuditFormSuccessMixin, CreateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    form_class = OrganizationForm
    success_url = reverse_lazy("organization-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "organization"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class OrganizationUpdateView(AdminRequiredMixin, AuditFormSuccessMixin, UpdateView):
    model = Organization
    template_name = "task_app/organization_form.html"
    form_class = OrganizationForm
    success_url = reverse_lazy("organization-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "organization"

    def get_queryset(self):
        return organizations_for_user(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ProjectListView(ScopedAccessMixin, ListView):
    model = Project
    template_name = "task_app/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        queryset = projects_for_user(self.request.user).select_related("organization").annotate(task_total=Count("tasks", distinct=True))
        query = get_clean_query(self.request)
        active_filter = self.request.GET.get("active", "all")
        sort_value = self.request.GET.get("sort", "name")

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


class ProjectCreateView(ManagerRequiredMixin, AuditFormSuccessMixin, CreateView):
    model = Project
    template_name = "task_app/project_form.html"
    form_class = ProjectForm
    success_url = reverse_lazy("project-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "project"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class ProjectUpdateView(ManagerRequiredMixin, AuditFormSuccessMixin, UpdateView):
    model = Project
    template_name = "task_app/project_form.html"
    form_class = ProjectForm
    success_url = reverse_lazy("project-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "project"

    def get_queryset(self):
        return projects_for_user(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


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


class TaskStatusCreateView(ManagerRequiredMixin, AuditFormSuccessMixin, CreateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    form_class = TaskStatusForm
    success_url = reverse_lazy("taskstatus-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "task_status"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class TaskStatusUpdateView(ManagerRequiredMixin, AuditFormSuccessMixin, UpdateView):
    model = TaskStatus
    template_name = "task_app/taskstatus_form.html"
    form_class = TaskStatusForm
    success_url = reverse_lazy("taskstatus-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "task_status"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class TaskListView(ScopedAccessMixin, ListView):
    model = Task
    template_name = "task_app/task_list.html"
    context_object_name = "tasks"

    def get_queryset(self):
        queryset = tasks_for_user(self.request.user).select_related("project", "status", "assigned_to")
        query = get_clean_query(self.request)
        status_filter = self.request.GET.get("status", "all")
        priority_filter = self.request.GET.get("priority", "all")
        completion_filter = self.request.GET.get("completion", "all")
        due_filter = self.request.GET.get("due", "all")
        sort_value = self.request.GET.get("sort", "status")
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


class TaskCreateView(ManagerRequiredMixin, AuditFormSuccessMixin, CreateView):
    model = Task
    template_name = "task_app/task_form.html"
    form_class = TaskForm
    success_url = reverse_lazy("task-list")
    audit_action = AuditLog.ACTION_CREATE
    audit_entity_type = "task"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class TaskUpdateView(ManagerRequiredMixin, AuditFormSuccessMixin, UpdateView):
    model = Task
    template_name = "task_app/task_form.html"
    form_class = TaskForm
    success_url = reverse_lazy("task-list")
    audit_action = AuditLog.ACTION_UPDATE
    audit_entity_type = "task"

    def get_queryset(self):
        return tasks_for_user(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


def issue_secure_challenge(request):
    challenge = secrets.token_urlsafe(32)
    issued_at = timezone.now().isoformat()
    request.session["secure_challenge"] = challenge
    request.session["secure_challenge_issued_at"] = issued_at
    request.session["secure_verified_at"] = None
    return challenge


class SecureAccessPermissionMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_app(self.request.user)


def secure_access_view(request):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    if not can_manage_app(request.user):
        write_security_event(request, "protected_access_denied", SecurityEvent.SEVERITY_WARNING, "User lacks role for secure access page.")
        raise Http404("You do not have access to this page.")

    current_challenge = request.session.get("secure_challenge") or issue_secure_challenge(request)
    issued_at = request.session.get("secure_challenge_issued_at")

    if request.method == "POST":
        signature_b64 = request.POST.get("signature", "").strip()
        submitted_challenge = request.session.get("secure_challenge")
        if not submitted_challenge or not issued_at:
            messages.error(request, "Your secure challenge expired. Please try again.")
            issue_secure_challenge(request)
            return redirect("secure-access")

        issued_at_dt = timezone.datetime.fromisoformat(issued_at)
        if timezone.is_naive(issued_at_dt):
            issued_at_dt = timezone.make_aware(issued_at_dt, timezone.get_current_timezone())
        if timezone.now() > issued_at_dt + timedelta(minutes=5):
            write_security_event(request, "signature_challenge_expired", SecurityEvent.SEVERITY_WARNING, "Secure challenge expired before signature verification.")
            messages.error(request, "Your secure challenge expired. Please sign the new challenge.")
            issue_secure_challenge(request)
            return redirect("secure-access")

        try:
            public_key_data = settings.SECURE_ACCESS_PUBLIC_KEY_PATH.read_bytes()
            public_key = load_pem_public_key(public_key_data)
            signature = base64.b64decode(signature_b64)
            public_key.verify(
                signature,
                submitted_challenge.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            request.session["secure_verified_at"] = timezone.now().isoformat()
            request.session.pop("secure_challenge", None)
            request.session.pop("secure_challenge_issued_at", None)
            write_audit_log(
                user=request.user,
                action=AuditLog.ACTION_VERIFY,
                entity_type="protected_report",
                summary="RSA challenge verified successfully",
                metadata={"path": request.path},
            )
            write_security_event(request, "signature_verification_success", SecurityEvent.SEVERITY_INFO, "Protected report challenge verified successfully.")
            messages.success(request, "Signature verified successfully. Protected report access is temporarily unlocked.")
            return redirect("protected-report")
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
        raise Http404("You do not have access to this page.")

    verified_at_str = request.session.get("secure_verified_at")
    if not verified_at_str:
        messages.error(request, "You must verify a signed challenge before accessing this report.")
        return redirect("secure-access")

    verified_at = timezone.datetime.fromisoformat(verified_at_str)
    if timezone.is_naive(verified_at):
        verified_at = timezone.make_aware(verified_at, timezone.get_current_timezone())
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