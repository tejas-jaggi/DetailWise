from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("sign-in/", views.SignInView.as_view(), name="login"),
    path("sign-out/", views.SignOutView.as_view(), name="logout"),
]
