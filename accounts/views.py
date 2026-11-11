from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from bookings.selection import active_service_from_next

from .forms import RegistrationForm, SignInForm


def _safe_next(request, url: str | None) -> str:
    """Return `url` only if it stays on this site; otherwise an empty string."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return ""


def register(request):
    """S03 Register: create a customer account, then send the user to sign in."""
    if request.user.is_authenticated:
        return redirect("bookings:catalog")

    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next"))

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()  # creates the account but does NOT sign the user in
            messages.success(request, "Account created. Sign in to continue.")
            login_url = reverse("accounts:login")
            if next_url:
                login_url += "?" + urlencode({"next": next_url})
            return redirect(login_url)
    else:
        form = RegistrationForm()

    return render(request, "accounts/register.html", {
        "form": form,
        "next": next_url,
        "selected_service": active_service_from_next(next_url),
    })


class SignInView(LoginView):
    """S02 Sign In. Django's LoginView only follows same-site `next` URLs."""

    template_name = "accounts/login.html"
    authentication_form = SignInForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # Staff have no customer bookings; the staff dashboard comes later.
        if self.request.user.is_staff:
            return resolve_url("bookings:catalog")
        return resolve_url(settings.LOGIN_REDIRECT_URL)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_service"] = active_service_from_next(context.get("next"))
        return context


class SignOutView(LogoutView):
    """POST-only sign out (Django answers GET with 405)."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You have signed out.")
        return response
