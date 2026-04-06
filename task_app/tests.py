from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Organization, Project, Task, TaskStatus


# Model tests for core task relationships
class TaskModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
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