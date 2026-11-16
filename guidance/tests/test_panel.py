"""Tests for the booking-page weather panel (plan Task 8).

Django tests check the markup and the booking flow; static checks keep the JS
text-only and away from the booking form. The JS state logic is tested with
Node's built-in runner, run here when Node is installed.
"""

import re
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from bookings.models import Booking, Service
from bookings.tests.test_views import PASSWORD, future_date

User = get_user_model()
JS_FILES = ("js/guidance-state.js", "js/guidance.js")
CREATE_URL = reverse("bookings:create")


def static_text(name: str) -> str:
    return Path(finders.find(name)).read_text(encoding="utf-8")


class PanelTestCase(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)
        self.client.force_login(self.customer)

    def booking_page(self) -> str:
        response = self.client.get(CREATE_URL)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def panel(self, html: str) -> str:
        start = html.index('<section id="weather-panel"')
        return html[start:html.index("</section>", start)]


class PanelMarkupTests(PanelTestCase):
    def test_panel_renders_on_booking_page(self):
        html = self.booking_page()
        panel = self.panel(html)
        self.assertIn("Weather for your date", panel)
        self.assertIn("Fixed shop: Urbana, IL · Central Time", panel)
        self.assertIn("Forecast: Open-Meteo", panel)
        self.assertIn(f'data-forecast-url="{reverse("guidance:forecast")}"', panel)
        self.assertIn(f'data-explain-url="{reverse("guidance:explain")}"', panel)
        self.assertRegex(panel, r'id="weather-slot"[^>]*aria-live="polite"')
        self.assertRegex(panel, r'<button type="button" id="explain-btn"[^>]*disabled')
        self.assertIn("<noscript>", panel)
        for name in JS_FILES:
            self.assertRegex(html, rf'<script defer src="{settings.STATIC_URL}{name}">')

    def test_panel_points_at_the_booking_fields(self):
        panel = self.panel(self.booking_page())
        self.assertIn('data-service-input="id_service"', panel)
        self.assertIn('data-date-input="id_date"', panel)
        self.assertIn('data-time-input="id_time"', panel)
        self.assertRegex(panel, r'data-csrf-token="[A-Za-z0-9]{32,}"')

    def test_panel_outside_booking_form(self):
        html = self.booking_page()
        form_start = html.index(f'action="{CREATE_URL}"')
        form_end = html.index("</form>", form_start)
        self.assertGreater(html.index('<section id="weather-panel"'), form_end)
        panel = self.panel(html)
        self.assertNotIn("<form", panel)
        self.assertNotIn(" form=", panel)  # no button tied to the booking form

    def test_booking_form_markup_unchanged(self):
        html = self.booking_page()
        form = html[html.index(f'action="{CREATE_URL}"'):]
        form = form[:form.index("</form>")]
        self.assertEqual(re.findall(r'name="(\w+)"', form),
                         ["csrfmiddlewaretoken", "service", "date", "time"])
        self.assertEqual(form.count('type="submit"'), 1)
        self.assertIn("Save booking", form)
        self.assertNotIn("weather", form.lower())

    def test_booking_page_wraps_form_and_panel_in_layout(self):
        html = self.booking_page()
        layout = html.index('class="booking-layout"')
        self.assertLess(layout, html.index('class="panel form-panel"'))
        self.assertLess(layout, html.index('<section id="weather-panel"'))

    def test_panel_absent_on_other_pages(self):
        for url in (reverse("bookings:catalog"), reverse("bookings:my_bookings")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn("weather-panel", html)
                self.assertNotIn("guidance.js", html)

    def test_booking_save_still_works_with_panel(self):
        service = Service.objects.get(slug="exterior-wash")
        response = self.client.post(CREATE_URL, {
            "service": service.pk, "date": future_date().isoformat(), "time": "10:00",
        })
        self.assertRedirects(response, reverse("bookings:my_bookings"))
        self.assertEqual(Booking.objects.filter(customer=self.customer).count(), 1)

    def test_invalid_booking_rerenders_form_errors_and_panel(self):
        response = self.client.post(CREATE_URL, {"service": "", "date": "", "time": ""})
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your booking was not saved", html)
        self.assertIn("Choose a service.", html)
        self.assertIn('<section id="weather-panel"', html)
        self.assertEqual(Booking.objects.count(), 0)


class StaticSafetyTests(TestCase):
    def test_static_files_exist(self):
        for name in JS_FILES + ("css/components.css",):
            with self.subTest(name=name):
                self.assertIsNotNone(finders.find(name))

    def test_js_never_uses_innerhtml_with_data(self):
        unsafe = re.compile(
            r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function"
        )
        for name in JS_FILES:
            with self.subTest(name=name):
                self.assertIsNone(unsafe.search(static_text(name)))

    def test_js_sends_csrf_header(self):
        self.assertIn("X-CSRFToken", static_text("js/guidance.js"))

    def test_js_never_submits_or_changes_the_booking_form(self):
        script = static_text("js/guidance.js")
        for pattern in (r"\.submit\s*\(", r"requestSubmit", r"preventDefault",
                        r"\.value\s*=[^=]", r"querySelector\(\s*['\"]form",
                        r"\.form\b"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, script))

    def test_customer_text_does_not_imply_the_model_runs_on_the_customer_device(self):
        # The model runs wherever Django's OLLAMA_BASE_URL points, never in the browser.
        template = Path(settings.BASE_DIR, "templates", "guidance", "_weather_panel.html")
        texts = [static_text(name) for name in JS_FILES]
        texts.append(template.read_text(encoding="utf-8"))
        for text in texts:
            self.assertIsNone(re.search(r"local (AI )?model|on your (device|computer)",
                                        text, re.IGNORECASE))

    def test_panel_css_uses_tokens_only(self):
        css = static_text("css/components.css")
        start = css.index("/* ---------- Weather guidance panel")
        panel_css = css[start:]
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", panel_css))
        self.assertIn("@media (min-width: 56rem)", panel_css)


class NodeTests(TestCase):
    def test_node_state_tests_pass(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed")
        tests = Path(settings.BASE_DIR) / "guidance" / "tests" / "js"
        result = subprocess.run(
            [node, "--test", str(tests / "guidance_state.test.mjs")],
            capture_output=True, text=True, timeout=120, cwd=settings.BASE_DIR,
        )
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-2000:])
