from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """DetailWise account.

    No extra fields yet. It exists so the project owns its user model from the
    first migration (switching later is painful). Staff accounts are marked by
    the built-in `is_staff` flag; everyone else is a customer.
    """
