# Django Task Management Project

This project is a simple task-management application built with Django. It includes the following models:

- Organization
- Project
- TaskStatus
- Task

The project is designed to be demonstrated through the Django admin portal, as requested in class.

## Features

- Manage organizations
- Manage projects inside organizations
- Manage task statuses such as To Do, In Progress, and Completed
- Manage tasks with due dates, priorities, assignees, and status
- Demonstrate relationships between models in the Django admin portal

## Project Structure

- `task_manager/` contains the Django project configuration
- `task_app/` contains the application models, admin setup, and migrations

## Setup Instructions

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run migrations:
   ```bash
   python manage.py migrate
   ```
4. Create an admin user:
   ```bash
   python manage.py createsuperuser
   ```
5. Start the server:
   ```bash
   python manage.py runserver
   ```
6. Open the admin site:
   - `http://127.0.0.1:8000/admin/`

## Suggested Demo Flow for Video

1. Explain the design of each model and how they relate.
2. Log into Django admin.
3. Add an Organization.
4. Add a Project connected to that Organization.
5. Add TaskStatus entries such as To Do, In Progress, and Completed.
6. Add several Tasks connected to a Project and TaskStatus.
7. Show filtering, searching, and relationship navigation inside admin.

## Model Design Summary

### Organization
Stores the name and contact information for an organization.

### Project
Belongs to one organization and stores project details such as name, description, start date, end date, and whether it is active.

### TaskStatus
Stores reusable task states such as To Do, In Progress, Blocked, and Completed.

### Task
Belongs to one project and one status. It stores task details including title, description, due date, priority, completion state, and assignee.

## Notes

- This project uses Django's built-in `User` model for task assignment.
- The admin panel is configured to make demonstrations easy with list views, filters, and search fields.
