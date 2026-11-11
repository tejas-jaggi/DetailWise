from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("bookings/", views.my_bookings, name="my_bookings"),
    path("bookings/new/", views.booking_create, name="create"),
    path("bookings/<int:pk>/", views.booking_detail, name="detail"),
]
