from django.db import migrations


def create_or_update_member_test_user(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("task_app", "UserProfile")

    username = "testuser"
    email = "testuser@example.com"
    raw_password = "password"

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "is_staff": False,
            "is_superuser": False,
            "is_active": True,
        },
    )

    if not created:
        user.email = email
        user.is_staff = False
        user.is_superuser = False
        user.is_active = True

    user.set_password(raw_password)
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "MEMBER"
    profile.save()


def remove_member_test_user(apps, schema_editor):
    User = apps.get_model("auth", "User")
    User.objects.filter(username="testuser").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("task_app", "0003_auditlog_securityevent_userprofile"),
    ]

    operations = [
        migrations.RunPython(
            create_or_update_member_test_user,
            remove_member_test_user,
        ),
    ]