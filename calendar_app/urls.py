from django.urls import path

from .views import calendar_month_view


urlpatterns = [
    path("", calendar_month_view, name="calendar-month"),
]