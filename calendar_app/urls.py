"""URL routes for the calendar feature."""

from django.urls import path

from .views import calendar_month_view


urlpatterns = [
    # The calendar root intentionally maps to one view that switches modes via query params.
    path("", calendar_month_view, name="calendar-month"),
]
