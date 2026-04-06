from django.contrib import admin
from django.urls import include, path


# Project routes
urlpatterns = [
    path("admin/", admin.site.urls),
    path("calendar/", include("calendar_app.urls")),
    path("", include("task_app.urls")),
]