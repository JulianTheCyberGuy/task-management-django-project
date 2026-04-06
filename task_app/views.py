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

        context["organization_count"] = scoped_organizations.count()
        context["project_count"] = scoped_projects.count()
        context["status_count"] = TaskStatus.objects.count()
        context["task_count"] = scoped_tasks.count()
        context["completed_task_count"] = scoped_tasks.filter(is_completed=True).count()
        context["incomplete_task_count"] = scoped_tasks.filter(is_completed=False).count()
        context["recent_tasks"] = scoped_tasks.select_related("project", "status").order_by("-id")[:5]
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
        return organizations_for_user(self.request.user).order_by("name")


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
        return projects_for_user(self.request.user).select_related("organization").order_by("name")


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
    queryset = TaskStatus.objects.order_by("sort_order", "name")


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
        return tasks_for_user(self.request.user).select_related("project", "status", "assigned_to").order_by(
            "status__sort_order",
            "due_date",
            "title",
        )


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