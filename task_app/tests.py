import csv
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, Organization, Project, SecurityEvent, Task, TaskStatus, UserProfile


User = get_user_model()


class TaskModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="adminuser",
            email="admin@example.com",
            password="Password123!",
        )
        self.organization = Organization.objects.create(name="Acme Organization")
        self.project = Project.objects.create(
            organization=self.organization,
            name="Website Redesign",
        )
        self.status = TaskStatus.objects.create(name="To Do", sort_order=1)

    def test_create_task(self):
        task = Task.objects.create(
            project=self.project,
            status=self.status,
            title="Create homepage wireframe",
            assigned_to=self.user,
            priority=Task.PRIORITY_HIGH,
        )

        self.assertEqual(task.title, "Create homepage wireframe")
        self.assertEqual(task.project.name, "Website Redesign")
        self.assertEqual(str(task.status), "To Do")


class SecurityMonitoringViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="securityadmin",
            email="securityadmin@example.com",
            password="Password123!",
            is_staff=True,
            is_superuser=True,
        )
        self.member_user = User.objects.create_user(
            username="memberuser",
            email="member@example.com",
            password="Password123!",
        )

        self.organization = Organization.objects.create(name="Security Org")
        self.project = Project.objects.create(organization=self.organization, name="Security Project")
        self.status = TaskStatus.objects.create(name="In Review", sort_order=2)
        Task.objects.create(
            project=self.project,
            status=self.status,
            title="Review protected report flow",
            assigned_to=self.member_user,
        )

        AuditLog.objects.create(
            user=self.admin_user,
            action=AuditLog.ACTION_VIEW,
            entity_type="protected_report",
            entity_id="1",
            summary="Protected report viewed",
            metadata={"task_count": 1},
        )
        AuditLog.objects.create(
            user=self.admin_user,
            action=AuditLog.ACTION_DENIED,
            entity_type="protected_report",
            entity_id="1",
            summary="RSA challenge verification failed",
            metadata={"path": "/secure-access/"},
        )
        SecurityEvent.objects.create(
            user=self.admin_user,
            event_type="protected_report_viewed",
            severity=SecurityEvent.SEVERITY_INFO,
            ip_address="127.0.0.1",
            details="Protected report viewed with 1 task in scope.",
        )
        SecurityEvent.objects.create(
            user=self.member_user,
            event_type="protected_access_denied",
            severity=SecurityEvent.SEVERITY_WARNING,
            ip_address="127.0.0.2",
            details="User lacked role for secure access page.",
        )

    def test_security_dashboard_requires_admin(self):
        self.client.login(username="memberuser", password="Password123!")
        response = self.client.get(reverse("security-dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_security_dashboard_renders_for_admin(self):
        self.client.login(username="securityadmin", password="Password123!")
        response = self.client.get(reverse("security-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Security Dashboard")
        self.assertContains(response, "Protected Resource Events")

    def test_audit_log_view_filters_by_entity(self):
        self.client.login(username="securityadmin", password="Password123!")
        response = self.client.get(reverse("audit-log-list"), {"entity": "protected_report"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Protected report viewed")

    def test_security_event_view_filters_by_severity(self):
        self.client.login(username="securityadmin", password="Password123!")
        response = self.client.get(reverse("security-event-list"), {"severity": SecurityEvent.SEVERITY_WARNING})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "protected_access_denied")
        self.assertNotContains(response, "protected_report_viewed")

    def test_failed_access_view_shows_warning_event(self):
        self.client.login(username="securityadmin", password="Password123!")
        response = self.client.get(reverse("failed-access-list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "protected_access_denied")

    def test_protected_access_history_view_shows_protected_events(self):
        self.client.login(username="securityadmin", password="Password123!")
        response = self.client.get(reverse("protected-access-history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Protected Resource Access History")
        self.assertContains(response, "protected_report_viewed")


class CsvExportViewTests(TestCase):
    def setUp(self):
        self.password = "Password123!"
        self.org_alpha = Organization.objects.create(
            name="Alpha Org",
            contact_email="alpha@example.com",
            phone_number="555-0100",
        )
        self.org_beta = Organization.objects.create(
            name="Beta Org",
            contact_email="beta@example.com",
            phone_number="555-0101",
        )

        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password=self.password,
        )
        self.admin_user.profile.role = UserProfile.ROLE_ADMIN
        self.admin_user.profile.save()

        self.manager_user = User.objects.create_user(
            username="manager",
            email="manager@example.com",
            password=self.password,
        )
        self.manager_user.profile.role = UserProfile.ROLE_MANAGER
        self.manager_user.profile.organization = self.org_alpha
        self.manager_user.profile.save()

        self.member_user = User.objects.create_user(
            username="member",
            email="member@example.com",
            password=self.password,
        )
        self.member_user.profile.role = UserProfile.ROLE_MEMBER
        self.member_user.profile.organization = self.org_alpha
        self.member_user.profile.save()

        self.other_member_user = User.objects.create_user(
            username="othermember",
            email="othermember@example.com",
            password=self.password,
        )
        self.other_member_user.profile.role = UserProfile.ROLE_MEMBER
        self.other_member_user.profile.organization = self.org_beta
        self.other_member_user.profile.save()

        self.status_todo = TaskStatus.objects.create(name="To Do", sort_order=1)
        self.status_done = TaskStatus.objects.create(name="Done", sort_order=2)

        self.project_alpha = Project.objects.create(
            organization=self.org_alpha,
            name="Alpha Launch",
            description="Launch the alpha program",
            is_active=True,
        )
        self.project_beta = Project.objects.create(
            organization=self.org_beta,
            name="Beta Refresh",
            description="Refresh beta operations",
            is_active=False,
        )

        Task.objects.create(
            project=self.project_alpha,
            status=self.status_todo,
            title="Prepare alpha checklist",
            assigned_to=self.member_user,
            priority=Task.PRIORITY_HIGH,
            is_completed=False,
        )
        Task.objects.create(
            project=self.project_beta,
            status=self.status_done,
            title="Close beta backlog",
            assigned_to=self.other_member_user,
            priority=Task.PRIORITY_LOW,
            is_completed=True,
        )

    def _response_rows(self, response):
        content = response.content.decode("utf-8")
        return list(csv.reader(StringIO(content)))

    def test_admin_can_export_filtered_organizations_csv(self):
        self.client.login(username="admin", password=self.password)
        response = self.client.get(reverse("organization-export-csv"), {"q": "Alpha"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn('attachment; filename="organizations_export.csv"', response["Content-Disposition"])

        rows = self._response_rows(response)
        self.assertEqual(rows[0], ["ID", "Name", "Contact Email", "Phone Number", "Project Count", "Created At"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "Alpha Org")
        self.assertEqual(AuditLog.objects.filter(entity_type="organization_export").count(), 1)

    def test_manager_project_export_is_limited_to_organization_scope(self):
        self.client.login(username="manager", password=self.password)
        response = self.client.get(reverse("project-export-csv"))

        self.assertEqual(response.status_code, 200)
        rows = self._response_rows(response)
        exported_project_names = [row[1] for row in rows[1:]]

        self.assertEqual(exported_project_names, ["Alpha Launch"])
        self.assertNotIn("Beta Refresh", exported_project_names)

    def test_member_task_export_only_includes_assigned_tasks(self):
        self.client.login(username="member", password=self.password)
        response = self.client.get(reverse("task-export-csv"))

        self.assertEqual(response.status_code, 200)
        rows = self._response_rows(response)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "Prepare alpha checklist")
        self.assertEqual(rows[1][5], "member")

    def test_task_export_respects_completion_filter(self):
        self.client.login(username="admin", password=self.password)
        response = self.client.get(reverse("task-export-csv"), {"completion": "completed"})

        self.assertEqual(response.status_code, 200)
        rows = self._response_rows(response)
        exported_task_titles = [row[1] for row in rows[1:]]

        self.assertEqual(exported_task_titles, ["Close beta backlog"])
        self.assertEqual(AuditLog.objects.filter(entity_type="task_export").count(), 1)


class ApiEndpointTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="apiadmin",
            email="apiadmin@example.com",
            password="Password123!",
            is_superuser=True,
            is_staff=True,
        )
        self.manager_user = User.objects.create_user(
            username="apimanager",
            email="apimanager@example.com",
            password="Password123!",
        )
        self.member_user = User.objects.create_user(
            username="apimember",
            email="apimember@example.com",
            password="Password123!",
        )
        self.other_member_user = User.objects.create_user(
            username="othermemberapi",
            email="othermember@example.com",
            password="Password123!",
        )

        self.organization = Organization.objects.create(name="API Org")
        self.other_organization = Organization.objects.create(name="Other Org")

        self.manager_user.profile.organization = self.organization
        self.manager_user.profile.role = UserProfile.ROLE_MANAGER
        self.manager_user.profile.save()

        self.member_user.profile.organization = self.organization
        self.member_user.profile.role = UserProfile.ROLE_MEMBER
        self.member_user.profile.save()

        self.other_member_user.profile.organization = self.other_organization
        self.other_member_user.profile.role = UserProfile.ROLE_MEMBER
        self.other_member_user.profile.save()

        self.todo = TaskStatus.objects.create(name="API To Do", sort_order=1)
        self.done = TaskStatus.objects.create(name="API Done", sort_order=2)

        self.project = Project.objects.create(
            organization=self.organization,
            name="Milestone API Project",
            description="Frontend-ready project payload",
            is_active=True,
        )
        self.other_project = Project.objects.create(
            organization=self.other_organization,
            name="Hidden Project",
            is_active=True,
        )

        self.task = Task.objects.create(
            project=self.project,
            status=self.todo,
            title="Visible task",
            description="This task should appear in the scoped API response.",
            assigned_to=self.member_user,
            due_date=timezone.localdate() + timedelta(days=2),
            priority=Task.PRIORITY_HIGH,
        )
        Task.objects.create(
            project=self.other_project,
            status=self.done,
            title="Hidden task",
            assigned_to=self.other_member_user,
            due_date=timezone.localdate() + timedelta(days=5),
            priority=Task.PRIORITY_LOW,
            is_completed=True,
        )

        AuditLog.objects.create(
            user=self.admin_user,
            action=AuditLog.ACTION_VIEW,
            entity_type="task",
            entity_id=str(self.task.pk),
            summary="Viewed task in API test",
            metadata={"source": "test"},
        )

    def test_task_list_api_requires_authentication(self):
        response = self.client.get(reverse("api-task-list"))
        self.assertEqual(response.status_code, 403)

    def test_member_task_list_api_returns_only_assigned_tasks(self):
        self.client.login(username="apimember", password="Password123!")
        response = self.client.get(reverse("api-task-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["title"], "Visible task")

    def test_manager_project_list_api_is_scoped_to_organization(self):
        self.client.login(username="apimanager", password="Password123!")
        response = self.client.get(reverse("api-project-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["name"], "Milestone API Project")

    def test_calendar_events_api_supports_date_range_filter(self):
        self.client.login(username="apimanager", password="Password123!")
        start_date = timezone.localdate().isoformat()
        end_date = (timezone.localdate() + timedelta(days=7)).isoformat()

        response = self.client.get(reverse("api-calendar-events"), {
            "start": start_date,
            "end": end_date,
            "include_completed": "false",
        })

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "Visible task")

    def test_calendar_events_api_rejects_invalid_date_range(self):
        self.client.login(username="apimanager", password="Password123!")
        response = self.client.get(reverse("api-calendar-events"), {
            "start": "2026-05-10",
            "end": "2026-05-01",
        })

        self.assertEqual(response.status_code, 400)

    def test_audit_log_api_is_admin_only(self):
        self.client.login(username="apimanager", password="Password123!")
        response = self.client.get(reverse("api-audit-log-list"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_audit_log_api(self):
        self.client.login(username="apiadmin", password="Password123!")
        response = self.client.get(reverse("api-audit-log-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["summary"], "Viewed task in API test")
