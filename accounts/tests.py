import re
from html import unescape
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.permissions import customer_required, staff_required
from bookings.models import Service

User = get_user_model()
PASSWORD = "detail-wise-Test-9"
BOOK_NEXT = "/bookings/new/?service=exterior-wash"


def messages_of(response):
    return [str(m) for m in response.context["messages"]]


class RegistrationTests(TestCase):
    url = reverse("accounts:register")

    def post(self, **extra):
        data = {"username": "jordan", "password1": PASSWORD, "password2": PASSWORD}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_register_page_renders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create an account")

    def test_registration_creates_customer_with_hashed_password(self):
        self.post()
        user = User.objects.get(username="jordan")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(PASSWORD))

    def test_registration_never_creates_staff(self):
        self.post(is_staff="on", is_superuser="on")
        user = User.objects.get(username="jordan")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registration_does_not_sign_user_in(self):
        response = self.post()
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)

    def test_registration_shows_success_message_on_sign_in_page(self):
        response = self.client.post(
            self.url,
            {"username": "jordan", "password1": PASSWORD, "password2": PASSWORD},
            follow=True,
        )
        self.assertIn("Account created. Sign in to continue.", messages_of(response))

    def test_short_password_rejected_with_field_error(self):
        response = self.post(password1="short1", password2="short1")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="jordan").exists())
        self.assertIn("password2", response.context["form"].errors)

    def test_password_mismatch_rejected(self):
        response = self.post(password2="different-Pass-9")
        self.assertFalse(User.objects.filter(username="jordan").exists())
        self.assertIn("password2", response.context["form"].errors)

    def test_duplicate_username_rejected(self):
        User.objects.create_user("jordan", password=PASSWORD)
        response = self.post()
        self.assertIn("username", response.context["form"].errors)

    def test_register_preserves_safe_next(self):
        response = self.post(next=BOOK_NEXT)
        expected = reverse("accounts:login") + "?next=" + quote(BOOK_NEXT, safe="")
        self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_register_ignores_unsafe_next(self):
        response = self.post(next="https://evil.example/steal")
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)


class AuthenticationNavigationTests(TestCase):
    booking_url = reverse("bookings:create") + "?service=full-detail"

    def header_link(self, response, label):
        header = response.content.decode().split("</header>", 1)[0]
        match = re.search(r'<a class="nav-btn" href="([^"]+)"[^>]*>' + label + r'</a>', header)
        self.assertIsNotNone(match, f"Missing header link: {label}")
        return unescape(match.group(1))

    def test_header_register_keeps_service_through_registration_and_login(self):
        response = self.client.get(self.booking_url, follow=True)
        register_url = self.header_link(response, "Register")
        self.assertEqual(register_url, reverse("accounts:register") + "?next="
                         + quote(self.booking_url, safe=""))
        response = self.client.get(register_url)
        self.assertEqual(response.context["selected_service"].slug, "full-detail")
        response = self.client.post(register_url, {
            "username": "jordan", "password1": PASSWORD, "password2": PASSWORD,
            "next": response.context["next"],
        }, follow=True)
        self.assertEqual(response.context["next"], self.booking_url)
        response = self.client.post(response.request["PATH_INFO"], {
            "username": "jordan", "password": PASSWORD, "next": response.context["next"],
        }, follow=True)
        self.assertRedirects(response, self.booking_url)
        self.assertEqual(response.context["form"].initial["service"],
                         Service.objects.get(slug="full-detail").pk)

    def test_header_sign_in_keeps_service_from_registration(self):
        User.objects.create_user("casey", password=PASSWORD)
        response = self.client.get(reverse("accounts:register"), {"next": self.booking_url})
        login_url = self.header_link(response, "Sign In")
        self.assertEqual(login_url, reverse("accounts:login") + "?next="
                         + quote(self.booking_url, safe=""))
        response = self.client.get(login_url)
        self.assertEqual(response.context["selected_service"].slug, "full-detail")
        response = self.client.post(login_url, {
            "username": "casey", "password": PASSWORD, "next": response.context["next"],
        }, follow=True)
        self.assertRedirects(response, self.booking_url)
        self.assertEqual(response.context["form"].initial["service"],
                         Service.objects.get(slug="full-detail").pk)

    def test_header_authentication_links_omit_absent_or_unsafe_next(self):
        for page in ("accounts:login", "accounts:register"):
            for next_url in ("", "https://evil.example/steal", "//evil.example/steal"):
                with self.subTest(page=page, next=next_url):
                    response = self.client.get(reverse(page), {"next": next_url})
                    self.assertEqual(self.header_link(response, "Sign In"),
                                     reverse("accounts:login"))
                    self.assertEqual(self.header_link(response, "Register"),
                                     reverse("accounts:register"))


class LoginLogoutTests(TestCase):
    url = reverse("accounts:login")

    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.staff = User.objects.create_user("sam", password=PASSWORD, is_staff=True)

    def test_customer_login_signs_in_and_goes_to_my_bookings(self):
        response = self.client.post(self.url, {"username": "casey", "password": PASSWORD})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.customer.pk)
        self.assertRedirects(response, reverse("bookings:my_bookings"), fetch_redirect_response=False)

    def test_staff_login_goes_to_catalog(self):
        response = self.client.post(self.url, {"username": "sam", "password": PASSWORD})
        self.assertRedirects(response, reverse("bookings:catalog"), fetch_redirect_response=False)

    def test_login_follows_safe_next(self):
        response = self.client.post(
            self.url, {"username": "casey", "password": PASSWORD, "next": BOOK_NEXT}
        )
        self.assertRedirects(response, BOOK_NEXT, fetch_redirect_response=False)

    def test_login_ignores_unsafe_next(self):
        response = self.client.post(
            self.url, {"username": "casey", "password": PASSWORD, "next": "https://evil.example/"}
        )
        self.assertRedirects(response, reverse("bookings:my_bookings"), fetch_redirect_response=False)

    def test_failed_login_shows_message_keeps_username_clears_password(self):
        response = self.client.post(self.url, {"username": "casey", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Username or password is incorrect.")
        self.assertContains(response, 'value="casey"')
        self.assertNotContains(response, "wrong-password")

    def test_sign_in_page_says_selected_service_is_kept(self):
        response = self.client.get(self.url, {"next": BOOK_NEXT})
        self.assertContains(response, "Your selected service (Exterior Wash) will be kept.")

    def test_logout_requires_post(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_post_signs_out(self):
        self.client.force_login(self.customer)
        response = self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(response, reverse("bookings:catalog"), fetch_redirect_response=False)


def ok_view(request):
    return HttpResponse("ok")


class PermissionDecoratorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.staff = User.objects.create_user("sam", password=PASSWORD, is_staff=True)

    def request_as(self, user):
        request = self.factory.get("/somewhere/")
        request.user = user
        return request

    def test_customer_required_redirects_anonymous_to_sign_in(self):
        response = customer_required(ok_view)(self.request_as(AnonymousUser()))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_customer_required_blocks_staff(self):
        with self.assertRaises(PermissionDenied):
            customer_required(ok_view)(self.request_as(self.staff))

    def test_customer_required_allows_customer(self):
        self.assertEqual(customer_required(ok_view)(self.request_as(self.customer)).status_code, 200)

    def test_staff_required_blocks_customer(self):
        with self.assertRaisesMessage(PermissionDenied, "Staff access required"):
            staff_required(ok_view)(self.request_as(self.customer))

    def test_staff_required_allows_staff(self):
        self.assertEqual(staff_required(ok_view)(self.request_as(self.staff)).status_code, 200)

    def test_staff_required_redirects_anonymous(self):
        self.assertEqual(staff_required(ok_view)(self.request_as(AnonymousUser())).status_code, 302)
