# Task Management Django Project

A role-aware Django task management application for tracking organizations, projects, tasks, statuses, and security activity. The project includes both a server-rendered web interface and a small authenticated API surface for scoped project, task, calendar, and audit log access.

## Core Features

- Organization, project, task status, and task management
- Role-based access for administrators, managers, and members
- User profile management and organization scoping
- Dashboard metrics for task health, deadlines, and status summaries
- CSV exports for organizations, projects, and tasks
- Security dashboard with audit logs and security events
- Protected report flow backed by signed challenge verification
- Authenticated API endpoints for projects, tasks, calendar events, and audit logs

## Tech Stack

- Python
- Django
- Django REST Framework
- SQLite by default
- Cryptography for secure access verification

## Project Layout

```text
task-management-django-project/
├── calendar_app/         # Calendar page views and routes
├── task_app/             # Main domain models, forms, views, API, and templates
├── task_manager/         # Django settings, root URLs, and WSGI/ASGI config
├── manage.py
├── requirements.txt
└── README.md
```

## Data Model Overview

### Organization
Stores the top-level organization record and contact details.

### UserProfile
Extends the Django user model with role and organization membership.

### Project
Belongs to an organization and stores lifecycle information such as start date, end date, and active state.

### TaskStatus
Stores reusable workflow states such as To Do, In Progress, and Completed.

### Task
Represents a unit of work inside a project with status, assignee, due date, priority, and completion state.

### AuditLog
Captures auditable actions across the app.

### SecurityEvent
Captures security-related events such as access denials, verification failures, and protected resource activity.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Apply migrations:

   ```bash
   python manage.py migrate
   ```

4. Create a superuser if needed:

   ```bash
   python manage.py createsuperuser
   ```

5. Start the development server:

   ```bash
   python manage.py runserver
   ```

6. Open the app in your browser:

   ```text
   http://127.0.0.1:8000/
   ```

## Default Workflow

1. Sign in as an administrator.
2. Create one or more organizations.
3. Create users and assign organization-scoped roles.
4. Create projects inside organizations.
5. Define task statuses.
6. Create and assign tasks.
7. Review dashboards, exports, and audit activity.

## API Summary

The application includes authenticated endpoints for:

- Scoped project list and detail
- Scoped task list and detail
- Calendar task event feed
- Admin-only audit log list and detail

API routes are mounted under the application URL configuration. Authentication and queryset scope are enforced server-side.

## Refactor Notes

This version includes a cleanup pass focused on reducing repeated logic and making the codebase easier to maintain.

- Centralized repeated form styling behavior into shared form mixins
- Centralized repeated role-denial handling into a reusable access mixin
- Centralized repeated `get_form_kwargs()` user injection for create and update views
- Centralized repeated session timestamp parsing used by protected access flows
- Expanded the README to reflect the current feature set instead of only the initial CRUD/admin scope

## Running Tests

```bash
python manage.py test
```

## Notes

- The application uses Django's built-in user model plus a `UserProfile` extension.
- Role scoping is enforced in both the UI layer and API querysets.
- Protected report access depends on the configured public key path in settings.
