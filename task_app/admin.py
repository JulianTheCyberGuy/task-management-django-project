from django.contrib import admin
from .models import Organization, Project, Task, TaskStatus


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_email', 'phone_number', 'created_at')
    search_fields = ('name', 'contact_email')
    ordering = ('name',)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'is_active', 'start_date', 'end_date')
    list_filter = ('is_active', 'organization')
    search_fields = ('name', 'organization__name', 'description')
    autocomplete_fields = ('organization',)


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order', 'description')
    ordering = ('sort_order', 'name')
    search_fields = ('name',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'status', 'priority', 'assigned_to', 'due_date', 'is_completed')
    list_filter = ('status', 'priority', 'is_completed', 'project__organization')
    search_fields = ('title', 'description', 'project__name', 'project__organization__name')
    autocomplete_fields = ('project', 'status', 'assigned_to')
    list_editable = ('status', 'priority', 'is_completed', 'due_date')
