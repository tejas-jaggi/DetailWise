"""Configuration checks without reading .env or connecting to either database.

Settings are loaded into an isolated namespace so environment cases do not alter
the application's active settings. The static-file test writes only to a
temporary directory; request tests use signed-cookie sessions without a database.
"""

import io
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from unittest import mock

from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.wsgi import WSGIHandler
from django.core.management import call_command
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import path


SETTINGS_FILE = Path(__file__).with_name("settings.py")
TEST_SECRET = "configuration-test-only-key-0123456789-abcdefghijklmnopqrstuvwxyz"
PRODUCTION_HOST = "detailwise.example"
POSTGRES_ENV = {
    "DJANGO_DB_ENGINE": "postgresql",
    "POSTGRES_DB": "detailwise_test_configuration",
    "POSTGRES_USER": "configuration_test_user",
    "POSTGRES_PASSWORD": " configuration-test-only:@/# password ",
    "POSTGRES_HOST": "db.example.invalid",
}


def load_configuration(**environ):
    values = {
        "DJANGO_SECRET_KEY": TEST_SECRET,
        "DJANGO_READ_DOT_ENV": "False",
        **environ,
    }
    with mock.patch.dict(os.environ, values, clear=True), mock.patch(
        "dotenv.load_dotenv"
    ):
        return runpy.run_path(str(SETTINGS_FILE))


def production_configuration(**environ):
    return load_configuration(
        **{"DJANGO_ALLOWED_HOSTS": PRODUCTION_HOST, **environ}
    )


def security_probe(request):
    get_token(request)
    request.session["configuration_test"] = "ok"
    return HttpResponse("ok")


urlpatterns = [path("security-probe/", security_probe)]


class DatabaseConfigurationTests(SimpleTestCase):
    def test_sqlite_is_the_default_even_with_unused_postgres_variables(self):
        for environ in ({}, {key: value for key, value in POSTGRES_ENV.items()
                             if key != "DJANGO_DB_ENGINE"}):
            with self.subTest(environ_keys=sorted(environ)):
                config = production_configuration(**environ)
                self.assertEqual(config["DATABASES"]["default"], {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": SETTINGS_FILE.parent.parent / "db.sqlite3",
                })

    def test_explicit_sqlite_preserves_the_local_database_path(self):
        config = load_configuration(DJANGO_DEBUG="True", DJANGO_DB_ENGINE="sqlite")
        self.assertEqual(config["DATABASES"]["default"]["NAME"],
                         SETTINGS_FILE.parent.parent / "db.sqlite3")

    def test_postgresql_configuration_uses_environment_and_secure_defaults(self):
        database = production_configuration(**POSTGRES_ENV)["DATABASES"]["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        for setting, variable in (
            ("NAME", "POSTGRES_DB"), ("USER", "POSTGRES_USER"),
            ("PASSWORD", "POSTGRES_PASSWORD"), ("HOST", "POSTGRES_HOST"),
        ):
            self.assertEqual(database[setting], POSTGRES_ENV[variable])
        self.assertEqual(str(database["PORT"]), "5432")
        self.assertEqual(database["CONN_MAX_AGE"], 60)
        self.assertTrue(database["CONN_HEALTH_CHECKS"])
        self.assertEqual(database["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(database["OPTIONS"]["connect_timeout"], 10)

    def test_postgresql_connection_options_can_be_overridden(self):
        database = production_configuration(
            **POSTGRES_ENV, POSTGRES_PORT="6543", DJANGO_DB_CONN_MAX_AGE="0",
            DJANGO_DB_CONNECT_TIMEOUT="25", DJANGO_DB_SSLMODE="verify-ca",
            DJANGO_DB_SSLROOTCERT="/run/certificates/database-ca.pem",
        )["DATABASES"]["default"]
        self.assertEqual(str(database["PORT"]), "6543")
        self.assertEqual(database["CONN_MAX_AGE"], 0)
        self.assertEqual(database["OPTIONS"], {
            "sslmode": "verify-ca", "connect_timeout": 25,
            "sslrootcert": "/run/certificates/database-ca.pem",
        })

    def test_missing_postgresql_fields_fail_without_exposing_passwords(self):
        for name in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST"):
            for value in (None, ""):
                environ = dict(POSTGRES_ENV)
                if value is None:
                    del environ[name]
                else:
                    environ[name] = value
                with self.subTest(name=name, missing=value is None):
                    with self.assertRaises(ImproperlyConfigured) as raised:
                        production_configuration(**environ)
                    self.assertIn(name, str(raised.exception))
                    self.assertNotIn(POSTGRES_ENV["POSTGRES_PASSWORD"], str(raised.exception))

    def test_unknown_or_blank_database_engine_is_rejected(self):
        for value in ("", "mysql", "postgreql"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                production_configuration(DJANGO_DB_ENGINE=value)

    def test_invalid_connection_numbers_are_rejected(self):
        cases = {
            "POSTGRES_PORT": ("0", "-1", "65536", "5432.5", "invalid", ""),
            "DJANGO_DB_CONN_MAX_AGE": ("-1", "1.5", "invalid", ""),
            "DJANGO_DB_CONNECT_TIMEOUT": ("0", "-1", "1.5", "invalid", ""),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ImproperlyConfigured):
                    production_configuration(**{**POSTGRES_ENV, name: value})

    def test_ssl_modes_are_explicit_and_validated(self):
        for mode in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
            with self.subTest(mode=mode):
                database = production_configuration(
                    **POSTGRES_ENV, DJANGO_DB_SSLMODE=mode
                )["DATABASES"]["default"]
                self.assertEqual(database["OPTIONS"]["sslmode"], mode)
        for mode in ("", "required", "verify_full"):
            with self.subTest(mode=mode), self.assertRaises(ImproperlyConfigured):
                production_configuration(**POSTGRES_ENV, DJANGO_DB_SSLMODE=mode)


class SecurityConfigurationTests(SimpleTestCase):
    def test_local_development_keeps_http_and_unhashed_static_files(self):
        config = load_configuration(DJANGO_DEBUG="True")
        self.assertTrue(config["DEBUG"])
        self.assertEqual(config["ALLOWED_HOSTS"], ["localhost", "127.0.0.1"])
        for name in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            self.assertFalse(config[name])
        self.assertEqual(config["STORAGES"]["staticfiles"]["BACKEND"],
                         "django.contrib.staticfiles.storage.StaticFilesStorage")

    def test_production_defaults_require_https_but_do_not_assume_hsts_or_proxy(self):
        config = production_configuration()
        self.assertFalse(config["DEBUG"])
        for name in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            self.assertTrue(config[name])
        self.assertEqual(config["CSRF_TRUSTED_ORIGINS"], [])
        self.assertEqual(config["SECURE_HSTS_SECONDS"], 0)
        self.assertFalse(config["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(config["SECURE_HSTS_PRELOAD"])
        self.assertIsNone(config["SECURE_PROXY_SSL_HEADER"])

    def test_production_requires_explicit_nonwildcard_hosts(self):
        for environ in ({}, {"DJANGO_ALLOWED_HOSTS": ""},
                        {"DJANGO_ALLOWED_HOSTS": " , "},
                        {"DJANGO_ALLOWED_HOSTS": "*"},
                        {"DJANGO_ALLOWED_HOSTS": f"{PRODUCTION_HOST},*"}):
            with self.subTest(environ=environ), self.assertRaises(ImproperlyConfigured):
                load_configuration(**environ)

    def test_host_and_origin_lists_trim_whitespace_and_empty_entries(self):
        config = production_configuration(
            DJANGO_ALLOWED_HOSTS=" detailwise.example, , www.detailwise.example ,",
            DJANGO_CSRF_TRUSTED_ORIGINS=" https://frontend.example, , https://detailwise.example ,",
        )
        self.assertEqual(config["ALLOWED_HOSTS"],
                         ["detailwise.example", "www.detailwise.example"])
        self.assertEqual(config["CSRF_TRUSTED_ORIGINS"],
                         ["https://frontend.example", "https://detailwise.example"])

    def test_security_booleans_accept_explicit_true_and_false_values(self):
        pairs = (
            ("DJANGO_SECURE_SSL_REDIRECT", "SECURE_SSL_REDIRECT"),
            ("DJANGO_SESSION_COOKIE_SECURE", "SESSION_COOKIE_SECURE"),
            ("DJANGO_CSRF_COOKIE_SECURE", "CSRF_COOKIE_SECURE"),
            ("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "SECURE_HSTS_INCLUDE_SUBDOMAINS"),
            ("DJANGO_SECURE_HSTS_PRELOAD", "SECURE_HSTS_PRELOAD"),
        )
        for value, expected in (("1", True), (" true ", True), ("YES", True),
                                ("on", True), ("0", False), (" false ", False),
                                ("NO", False), ("off", False)):
            config = production_configuration(**{name: value for name, _ in pairs})
            for variable, setting in pairs:
                with self.subTest(variable=variable, value=value):
                    self.assertIs(config[setting], expected)

    def test_malformed_security_booleans_fail_instead_of_disabling_security(self):
        for name in (
            "DJANGO_DEBUG", "DJANGO_READ_DOT_ENV", "DJANGO_SECURE_SSL_REDIRECT",
            "DJANGO_SESSION_COOKIE_SECURE", "DJANGO_CSRF_COOKIE_SECURE",
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "DJANGO_SECURE_HSTS_PRELOAD",
            "DJANGO_TRUST_X_FORWARDED_PROTO",
        ):
            for value in ("", "tru", "2"):
                with self.subTest(name=name, value=value), self.assertRaises(ImproperlyConfigured):
                    production_configuration(**{name: value})

    def test_hsts_duration_requires_a_nonnegative_whole_number(self):
        for value in ("-1", "1.5", "invalid", ""):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                production_configuration(DJANGO_SECURE_HSTS_SECONDS=value)
        config = production_configuration(DJANGO_SECURE_HSTS_SECONDS="300")
        self.assertEqual(config["SECURE_HSTS_SECONDS"], 300)
        self.assertFalse(config["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(config["SECURE_HSTS_PRELOAD"])

    def test_proxy_header_requires_explicit_trust(self):
        config = production_configuration(DJANGO_TRUST_X_FORWARDED_PROTO="True")
        self.assertEqual(config["SECURE_PROXY_SSL_HEADER"],
                         ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_dotenv_loading_can_be_disabled_and_remains_enabled_by_default(self):
        for value, should_load in ((None, True), ("True", True), ("False", False)):
            environ = {"DJANGO_SECRET_KEY": TEST_SECRET, "DJANGO_DEBUG": "True"}
            if value is not None:
                environ["DJANGO_READ_DOT_ENV"] = value
            with self.subTest(value=value), mock.patch.dict(os.environ, environ, clear=True), \
                    mock.patch("dotenv.load_dotenv") as dotenv:
                runpy.run_path(str(SETTINGS_FILE))
                self.assertEqual(dotenv.call_count, int(should_load))

    def test_secret_key_still_has_no_fallback(self):
        with self.assertRaises(ImproperlyConfigured):
            production_configuration(DJANGO_SECRET_KEY="")


class SecurityRequestTests(SimpleTestCase):
    def client_for_configuration(self, **environ):
        config = production_configuration(**environ)
        names = (
            "DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS",
            "SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE",
            "SECURE_HSTS_SECONDS", "SECURE_HSTS_INCLUDE_SUBDOMAINS",
            "SECURE_HSTS_PRELOAD", "SECURE_PROXY_SSL_HEADER",
        )
        self.enterContext(override_settings(
            **{name: config[name] for name in names},
            ROOT_URLCONF=__name__,
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
            MIDDLEWARE=[
                "django.middleware.security.SecurityMiddleware",
                "django.contrib.sessions.middleware.SessionMiddleware",
                "django.middleware.common.CommonMiddleware",
                "django.middleware.csrf.CsrfViewMiddleware",
            ],
        ))
        return Client(enforce_csrf_checks=True, HTTP_HOST=PRODUCTION_HOST)

    def test_http_redirects_to_https_and_https_issues_secure_cookies(self):
        client = self.client_for_configuration()
        response = client.get("/security-probe/?next=booking")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"],
                         f"https://{PRODUCTION_HOST}/security-probe/?next=booking")
        response = client.get("/security-probe/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["secure"])
        self.assertNotIn("Strict-Transport-Security", response)

    def test_untrusted_hosts_are_rejected(self):
        client = self.client_for_configuration()
        response = client.get("/security-probe/", secure=True, HTTP_HOST="untrusted.invalid")
        self.assertEqual(response.status_code, 400)

    def test_csrf_accepts_configured_origin_and_rejects_untrusted_origin(self):
        client = self.client_for_configuration(
            DJANGO_CSRF_TRUSTED_ORIGINS="https://frontend.example"
        )
        response = client.get("/security-probe/", secure=True)
        token = response.cookies["csrftoken"].value
        for origin, expected in (("https://untrusted.invalid", 403),
                                 ("https://frontend.example", 200)):
            with self.subTest(origin=origin):
                response = client.post(
                    "/security-probe/", secure=True, HTTP_ORIGIN=origin,
                    HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(response.status_code, expected)

    def test_forwarded_https_is_ignored_without_proxy_trust(self):
        client = self.client_for_configuration()
        response = client.get("/security-probe/", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 301)

    def test_trusted_forwarded_https_avoids_a_redirect_loop(self):
        client = self.client_for_configuration(DJANGO_TRUST_X_FORWARDED_PROTO="True")
        response = client.get("/security-probe/", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code, 200)

    def test_hsts_header_respects_explicit_deployment_decisions(self):
        client = self.client_for_configuration(DJANGO_SECURE_HSTS_SECONDS="300")
        response = client.get("/security-probe/", secure=True)
        self.assertEqual(response["Strict-Transport-Security"], "max-age=300")
        client = self.client_for_configuration(
            DJANGO_SECURE_HSTS_SECONDS="300",
            DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="True",
            DJANGO_SECURE_HSTS_PRELOAD="True",
        )
        response = client.get("/security-probe/", secure=True)
        self.assertEqual(response["Strict-Transport-Security"],
                         "max-age=300; includeSubDomains; preload")


class ProductionStaticFilesTests(SimpleTestCase):
    def test_production_storage_and_middleware_order(self):
        config = production_configuration()
        security_index = config["MIDDLEWARE"].index("django.middleware.security.SecurityMiddleware")
        self.assertEqual(config["MIDDLEWARE"][security_index + 1],
                         "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertEqual(config["STORAGES"]["default"]["BACKEND"],
                         "django.core.files.storage.FileSystemStorage")
        self.assertEqual(config["STORAGES"]["staticfiles"]["BACKEND"],
                         "whitenoise.storage.CompressedManifestStaticFilesStorage")

    def test_collectstatic_and_wsgi_serve_a_hashed_asset_without_database_access(self):
        config = production_configuration()
        with TemporaryDirectory(prefix="detailwise-static-test-") as static_root, override_settings(
            DEBUG=False, SECRET_KEY=TEST_SECRET, ALLOWED_HOSTS=[PRODUCTION_HOST],
            STATIC_ROOT=static_root, STATIC_URL=config["STATIC_URL"],
            STATICFILES_DIRS=config["STATICFILES_DIRS"], STORAGES=config["STORAGES"],
            MIDDLEWARE=config["MIDDLEWARE"], SECURE_SSL_REDIRECT=True,
            SECURE_PROXY_SSL_HEADER=None,
        ):
            call_command("collectstatic", interactive=False, verbosity=0, stdout=io.StringIO())
            self.assertTrue(Path(static_root, "staticfiles.json").is_file())
            url = staticfiles_storage.url("css/base.css")
            self.assertRegex(url, r"/css/base\.[a-f0-9]{12}\.css$")
            request = RequestFactory().get(url, secure=True, HTTP_HOST=PRODUCTION_HOST)
            captured = {}

            def start_response(status, headers, exc_info=None):
                captured["status"] = status
                captured["headers"] = dict(headers)

            response = WSGIHandler()(request.environ, start_response)
            try:
                content = b"".join(response)
            finally:
                response.close()
            self.assertEqual(captured["status"], "200 OK")
            self.assertIn("text/css", captured["headers"]["Content-Type"])
            self.assertIn("immutable", captured["headers"]["Cache-Control"])
            self.assertEqual(content, Path(config["BASE_DIR"], "static", "css", "base.css").read_bytes())
