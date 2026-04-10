from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .access import manageable_users_for_user, organizations_for_user, projects_for_user
from .models import Organization, Project, Task, TaskStatus, UserProfile


User = get_user_model()


class StyledModelForm(forms.ModelForm):
    date_input_type = "date"

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 4)
            if isinstance(widget, forms.DateInput):
                widget.input_type = self.date_input_type
            existing_class = widget.attrs.get("class", "")
            widget.attrs["class"] = (existing_class + " form-control").strip()


class OrganizationForm(StyledModelForm):
    class Meta:
        model = Organization
        fields = ["name", "contact_email", "phone_number"]


class ProjectForm(StyledModelForm):
    class Meta:
        model = Project
        fields = ["organization", "name", "description", "start_date", "end_date", "is_active"]
        widgets = {
            "start_date": forms.DateInput(),
            "end_date": forms.DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user is not None:
            self.fields["organization"].queryset = organizations_for_user(self.user)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be earlier than the start date.")
        return cleaned_data


class TaskStatusForm(StyledModelForm):
    class Meta:
        model = TaskStatus
        fields = ["name", "description", "sort_order"]


class TaskForm(StyledModelForm):
    class Meta:
        model = Task
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
        widgets = {
            "due_date": forms.DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user is not None:
            self.fields["project"].queryset = projects_for_user(self.user).select_related("organization")
            self.fields["assigned_to"].queryset = manageable_users_for_user(self.user)

    def clean(self):
        cleaned_data = super().clean()
        project = cleaned_data.get("project")
        due_date = cleaned_data.get("due_date")
        if project and not project.is_active and not self.instance.pk:
            self.add_error("project", "New tasks cannot be added to an inactive project.")
        if project and due_date:
            if project.start_date and due_date < project.start_date:
                self.add_error("due_date", "Due date cannot be earlier than the project start date.")
            if project.end_date and due_date > project.end_date:
                self.add_error("due_date", "Due date cannot be later than the project end date.")
        return cleaned_data


class AdminUserManagementForm(StyledModelForm):
    class Meta:
        model = UserProfile
        fields = ["role", "organization", "organizations"]
        widgets = {
            "organizations": forms.SelectMultiple(attrs={"size": 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization_queryset = Organization.objects.order_by("name")
        self.fields["organization"].queryset = organization_queryset
        self.fields["organization"].empty_label = "No primary organization assigned"
        self.fields["organizations"].queryset = organization_queryset
        self.fields["organizations"].required = False
        self.fields["organizations"].help_text = "Hold Command or Ctrl to select multiple organizations."

    def clean(self):
        cleaned_data = super().clean()
        primary_organization = cleaned_data.get("organization")
        organizations = cleaned_data.get("organizations")
        if primary_organization and organizations is not None and primary_organization not in organizations:
            self.add_error("organizations", "The primary organization must also be included in the allowed organizations list.")
        return cleaned_data


class SignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    organizations = forms.ModelMultipleChoiceField(
        queryset=Organization.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select at least one organization to access after signup.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "organizations", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organizations"].queryset = Organization.objects.order_by("name")
        self.fields["organizations"].label = "Organizations"
        self.fields["organizations"].widget.attrs["class"] = "organization-checkbox-list"
        for field_name, field in self.fields.items():
            if field_name == "organizations":
                continue
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (existing_class + " form-control").strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean_organizations(self):
        organizations = self.cleaned_data.get("organizations")
        if not organizations:
            raise forms.ValidationError("Select at least one organization to continue.")
        return organizations

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip().lower()
        if commit:
            user.save()
            profile = user.profile
            selected_organizations = list(self.cleaned_data["organizations"])
            profile.organization = selected_organizations[0]
            profile.role = UserProfile.ROLE_MEMBER
            profile.save()
            profile.organizations.set(selected_organizations)
        return user


class ProfileUpdateForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (existing_class + " form-control").strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.exclude(pk=self.user.pk).filter(email__iexact=email).exists():
            raise forms.ValidationError("Another user is already using this email address.")
        return email

    def save(self):
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"].strip().lower()
        self.user.save(update_fields=["first_name", "last_name", "email"])
        return self.user
