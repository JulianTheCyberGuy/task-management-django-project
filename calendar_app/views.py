import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from task_app.access import tasks_for_user


class CalendarMonthBuilder:
    def __init__(self, year: int, month: int):
        self.year = year
        self.month = month
        self.calendar = calendar.Calendar(firstweekday=6)

    def build(self, tasks_by_date):
        weeks = []
        for week in self.calendar.monthdatescalendar(self.year, self.month):
            week_days = []
            for day_value in week:
                week_days.append(
                    {
                        "date": day_value,
                        "day_number": day_value.day,
                        "in_current_month": day_value.month == self.month,
                        "is_today": day_value == date.today(),
                        "tasks": tasks_by_date.get(day_value, []),
                    }
                )
            weeks.append(week_days)
        return weeks


def _safe_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _get_selected_date(request):
    today = date.today()
    year_value = _safe_int(request.GET.get("year"), today.year)
    month_value = _safe_int(request.GET.get("month"), today.month)
    day_value = _safe_int(request.GET.get("day"), 1)

    try:
        return date(year_value, month_value, day_value)
    except ValueError:
        try:
            return date(year_value, month_value, 1)
        except ValueError:
            return today


def _get_mode(request):
    mode = request.GET.get("view", "month").lower()
    if mode not in {"month", "week", "day", "list"}:
        return "month"
    return mode


def _build_tasks_by_date(task_queryset):
    tasks_by_date = {}
    for task in task_queryset:
        tasks_by_date.setdefault(task.due_date, []).append(task)
    return tasks_by_date


@login_required
def calendar_month_view(request):
    selected_date = _get_selected_date(request)
    mode = _get_mode(request)
    today = date.today()

    month_start = selected_date.replace(day=1)
    month_end = selected_date.replace(day=calendar.monthrange(selected_date.year, selected_date.month)[1])
    week_start = selected_date - timedelta(days=(selected_date.weekday() + 1) % 7)
    week_end = week_start + timedelta(days=6)

    if mode == "month":
        range_start, range_end = month_start, month_end
        previous_anchor = month_start - timedelta(days=1)
        next_anchor = month_end + timedelta(days=1)
        heading = selected_date.strftime("%B %Y")
    elif mode == "week":
        range_start, range_end = week_start, week_end
        previous_anchor = week_start - timedelta(days=7)
        next_anchor = week_start + timedelta(days=7)
        heading = f"Week of {week_start.strftime('%b %d, %Y')}"
    elif mode == "day":
        range_start = range_end = selected_date
        previous_anchor = selected_date - timedelta(days=1)
        next_anchor = selected_date + timedelta(days=1)
        heading = selected_date.strftime("%A, %B %d, %Y")
    else:
        range_start, range_end = month_start, month_end
        previous_anchor = month_start - timedelta(days=1)
        next_anchor = month_end + timedelta(days=1)
        heading = f"Task List for {selected_date.strftime('%B %Y')}"

    tasks = (
        tasks_for_user(request.user)
        .select_related("project", "status", "assigned_to")
        .filter(due_date__isnull=False, due_date__gte=range_start, due_date__lte=range_end)
        .order_by("due_date", "priority", "title")
    )
    tasks_by_date = _build_tasks_by_date(tasks)
    month_builder = CalendarMonthBuilder(selected_date.year, selected_date.month)
    month_weeks = month_builder.build(tasks_by_date)

    week_days = []
    for offset in range(7):
        day_value = week_start + timedelta(days=offset)
        week_days.append(
            {
                "date": day_value,
                "day_number": day_value.day,
                "label": day_value.strftime("%a"),
                "in_current_month": day_value.month == selected_date.month,
                "is_today": day_value == today,
                "tasks": tasks_by_date.get(day_value, []),
            }
        )

    context = {
        "view_mode": mode,
        "calendar_heading": heading,
        "month_weeks": month_weeks,
        "weekdays": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "week_days": week_days,
        "day_tasks": tasks_by_date.get(selected_date, []),
        "list_groups": [{"date": task_date, "tasks": day_tasks_group} for task_date, day_tasks_group in sorted(tasks_by_date.items())],
        "task_total": tasks.count(),
        "selected_date": selected_date,
        "selected_day": selected_date.day,
        "selected_month": selected_date.month,
        "selected_year": selected_date.year,
        "previous_day": previous_anchor.day,
        "previous_month": previous_anchor.month,
        "previous_year": previous_anchor.year,
        "next_day": next_anchor.day,
        "next_month": next_anchor.month,
        "next_year": next_anchor.year,
        "current_day": today.day,
        "current_month": today.month,
        "current_year": today.year,
    }
    return render(request, "calendar_app/calendar_month.html", context)