"""The approved visual design (Bochen's prototype) applied through shared tokens.

These tests pin the decisions that are easy to undo by accident: the approved
palette and radius, no unapproved accent, tokens-only component CSS, no shipped
font files, safe service illustrations, and the page structures that carry the
design (boxed header, illustrated catalog cards, centred sign-in forms).
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from bookings.models import Service

User = get_user_model()
PASSWORD = "detail-wise-Test-9"
STATIC_CSS = ("css/tokens.css", "css/base.css", "css/components.css")
SERVICE_ICONS = ("img/services/exterior.svg", "img/services/interior.svg",
                 "img/services/mixed.svg")


def static_text(name: str) -> str:
    return Path(finders.find(name)).read_text(encoding="utf-8")


def token(name: str) -> str:
    match = re.search(rf"--{name}:\s*([^;]+);", static_text("css/tokens.css"))
    return match.group(1).strip() if match else ""


class TokenTests(TestCase):
    def test_approved_palette_and_radius(self):
        expected = {
            "color-bg": "#0b0e14",
            "color-surface": "#131925",
            "color-surface-raised": "#1b2230",
            "color-input": "#0d111a",
            "color-border": "#303c50",
            "color-text": "#f1f4f8",
            "color-text-body": "#d0d8e3",
            "color-text-muted": "#a5b2c5",
            "color-accent": "#f4e900",
            "color-accent-hover": "#fff74e",
            "color-on-accent": "#101216",
            "color-info": "#59dce8",
            "color-danger": "#ff7b84",
            "radius": "3px",
        }
        for name, value in expected.items():
            with self.subTest(token=name):
                self.assertEqual(token(name).lower(), value)

    def test_unapproved_magenta_accent_is_gone(self):
        for name in STATIC_CSS:
            with self.subTest(file=name):
                css = static_text(name).lower()
                self.assertNotIn("#ff3d8b", css)
                self.assertNotIn("--color-highlight", css)

    def test_component_css_uses_tokens_only(self):
        # Raw colors live in tokens.css; base and components reference variables.
        for name in ("css/base.css", "css/components.css"):
            with self.subTest(file=name):
                css = re.sub(r"/\*.*?\*/", "", static_text(name), flags=re.S)
                self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css))

    def test_condensed_heading_font_uses_installed_fonts_only(self):
        # No font files are shipped or downloaded (licensing): system fallbacks only.
        self.assertIn('"Arial Narrow"', token("font-head"))
        for name in STATIC_CSS:
            with self.subTest(file=name):
                css = static_text(name)
                self.assertNotIn("@font-face", css)
                self.assertNotIn("url(", css)


class IllustrationTests(TestCase):
    def test_service_illustrations_are_plain_svg(self):
        for name in SERVICE_ICONS:
            with self.subTest(icon=name):
                svg = static_text(name)
                self.assertTrue(svg.lstrip().startswith("<svg"))
                self.assertIsNone(re.search(
                    r"<script|<foreignObject|\son\w+=|href=|url\(", svg, re.IGNORECASE))


class PageStructureTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user("casey", password=PASSWORD)

    def test_catalog_cards_have_illustration_package_and_full_width_book_button(self):
        html = self.client.get(reverse("bookings:catalog")).content.decode()
        for service in Service.objects.filter(is_active=True):
            with self.subTest(service=service.slug):
                icon = f"img/services/{service.weather_sensitivity}.svg"
                self.assertIn(f'src="{settings.STATIC_URL}{icon}"', html)
                link = f'{reverse("bookings:create")}?service={service.slug}'
                self.assertRegex(html, rf'<a class="btn btn--primary btn--block" href="{re.escape(link)}"')
        for label in ("Exterior package", "Interior package", "Combined package"):
            self.assertIn(label, html)
        # Illustrations are decorative: empty alt text and hidden from screen readers.
        self.assertEqual(html.count('alt=""'), Service.objects.filter(is_active=True).count())

    def test_header_is_the_boxed_brand_header(self):
        html = self.client.get(reverse("bookings:catalog")).content.decode()
        header = html[html.index('<header class="site-header"'):html.index("</header>")]
        self.assertIn('class="brand__name"', header)
        self.assertIn("Weather-aware car detailing", header)
        self.assertIn("Urbana, IL", header)
        self.assertIn('<svg class="brand__icon"', header)

    def test_every_page_links_the_brand_favicon(self):
        html = self.client.get(reverse("bookings:catalog")).content.decode()
        self.assertIn(f'<link rel="icon" href="{settings.STATIC_URL}img/favicon.svg" '
                      'type="image/svg+xml">', html)
        svg = static_text("img/favicon.svg")
        self.assertIsNone(re.search(r"<script|\son\w+=|href=", svg, re.IGNORECASE))

    def test_current_page_marked_in_navigation(self):
        self.client.force_login(self.customer)
        html = self.client.get(reverse("bookings:my_bookings")).content.decode()
        self.assertRegex(html, rf'href="{reverse("bookings:my_bookings")}"[^>]*aria-current="page"')

    def test_sign_in_and_register_use_centred_auth_layout(self):
        for url in (reverse("accounts:login"), reverse("accounts:register")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('class="auth-shell"', html)
                self.assertIn('class="panel auth-card"', html)
                self.assertRegex(html, r'<button type="submit" class="btn btn--primary btn--block"')

    def test_weather_panel_has_no_extra_label_above_its_heading(self):
        self.client.force_login(self.customer)
        html = self.client.get(reverse("bookings:create")).content.decode()
        panel = html[html.index('<section id="weather-panel"'):]
        panel = panel[:panel.index("</section>")]
        self.assertNotIn('class="eyebrow"', panel)
