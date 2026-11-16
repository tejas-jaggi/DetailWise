from django.urls import path

from . import staff_views, views

app_name = "bookings"

urlpatterns = [
    path("staff/", staff_views.dashboard, name="staff_dashboard"),
    path("staff/bookings.csv", staff_views.booking_export, name="staff_export"),
    path("", views.catalog, name="catalog"),
    path("bookings/", views.my_bookings, name="my_bookings"),
    path("bookings/new/", views.booking_create, name="create"),
    path("bookings/<int:pk>/", views.booking_detail, name="detail"),
    path("bookings/<int:pk>/edit/", views.booking_edit, name="edit"),
    path("bookings/<int:pk>/cancel/", views.booking_cancel, name="cancel"),
]
