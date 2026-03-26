from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=150, unique=True)
    contact_email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Project(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='projects'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'name')

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


class TaskStatus(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'Task statuses'

    def __str__(self):
        return self.name


class Task(models.Model):
    PRIORITY_LOW = 'LOW'
    PRIORITY_MEDIUM = 'MED'
    PRIORITY_HIGH = 'HIGH'

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    status = models.ForeignKey(
        TaskStatus,
        on_delete=models.PROTECT,
        related_name='tasks'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tasks'
    )
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=4, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'title']

    def __str__(self):
        return self.title
