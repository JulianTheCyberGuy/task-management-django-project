import os

from django.core.asgi import get_asgi_application


# ASGI application setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "task_manager.settings")

application = get_asgi_application()