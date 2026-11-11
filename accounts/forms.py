from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class RegistrationForm(UserCreationForm):
    """Public sign-up: username and password only.

    Only `username` and the two password fields exist on this form, so a
    browser cannot set `is_staff` or `is_superuser`. Django hashes the password
    (PBKDF2) and AUTH_PASSWORD_VALIDATORS enforce at least 8 characters.
    """

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)


class SignInForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Username or password is incorrect.",
    }
