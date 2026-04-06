from django.contrib import admin
from django.urls import include, path


# Project routes
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("task_app.urls")),
]