"""Weather guidance URLs: two customer-only JSON endpoints (plan Task 7, D7)."""

from django.urls import path

from . import views

app_name = "guidance"

urlpatterns = [
    path("forecast/", views.forecast, name="forecast"),
    path("explain/", views.explain, name="explain"),
]
