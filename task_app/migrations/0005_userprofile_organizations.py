from django.db import migrations, models


def backfill_profile_organizations(apps, schema_editor):
    UserProfile = apps.get_model("task_app", "UserProfile")
    for profile in UserProfile.objects.exclude(organization__isnull=True).iterator():
        profile.organizations.add(profile.organization)


class Migration(migrations.Migration):

    dependencies = [
        ("task_app", "0004_create_member_test_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="organizations",
            field=models.ManyToManyField(blank=True, help_text="Organizations this user can access inside the app.", related_name="member_user_profiles", to="task_app.organization"),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="organization",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="primary_user_profiles", to="task_app.organization"),
        ),
        migrations.RunPython(backfill_profile_organizations, migrations.RunPython.noop),
    ]
