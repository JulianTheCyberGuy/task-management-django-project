from django.db import migrations

def create_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')

    if not User.objects.filter(username='demo_admin').exists():
        User.objects.create_superuser(
            username='admin',
            email='demo_admin@test.com',
            password='admin123'
        )

class Migration(migrations.Migration):

    dependencies = [
        ('task_app', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_superuser),
    ]