# Production configuration

DetailWise supports Django 5.2 and Python 3.13 with PostgreSQL, WhiteNoise and
Waitress. SQLite remains the default, and the local `runserver` workflow is
unchanged when `DJANGO_DEBUG=True`. These changes prepare the application;
they do not provision hosting, transfer SQLite data, or establish a working
PostgreSQL/HTTPS deployment.

## Local development and tests

Keep the existing `.env` and `db.sqlite3`. For a new checkout only, copy
`.env.example` to `.env` and generate a secret as described in the README.
Use `DJANGO_DEBUG=True` and `DJANGO_DB_ENGINE=sqlite`. PostgreSQL variables
are ignored while SQLite is selected. Installing the driver does not require
a local PostgreSQL server.

```text
python -m pip install -r requirements.txt
python manage.py check
python manage.py test config
python manage.py test
python manage.py runserver
```

Tests use Django's temporary test database. Configuration tests isolate their
environment, and do not connect to PostgreSQL. The existing HTTP/page tests
expect the local configuration; Django's test runner changing `DEBUG` during
a run does not undo security/storage choices made when settings were imported.
Do not run the suite with production database credentials.

## Environment variables

Supply production values through the host's environment or secret store.
Use a fresh random secret key, keep it stable across application processes
and restarts, and never put it or a database password in source control.
The placeholder values below are examples, not deployable credentials.

Process variables override `.env` values. Set `DJANGO_READ_DOT_ENV=False` in
the **process environment** to prevent reading a local `.env` at all. Boolean
values accept `true/false`, `1/0`, `yes/no` or `on/off`, ignoring case and outer
whitespace; invalid or blank booleans fail startup. Integer settings also
reject invalid values instead of silently choosing a fallback.

| Variable | Default | Production use |
|---|---|---|
| `DJANGO_SECRET_KEY` | None; required | Unique generated key; never use the example placeholder. |
| `DJANGO_READ_DOT_ENV` | `True` | Set `False` in the process environment. |
| `DJANGO_DEBUG` | `False` | Keep `False`. Use `True` only locally. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` only with debug enabled | Required with debug disabled. Comma-separated host names, without scheme/path/port. `*` is rejected in production. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Empty | Comma-separated trusted origins including scheme, e.g. `https://detailwise.example.com`. Include a port if nonstandard. |
| `DJANGO_SECURE_SSL_REDIRECT` | `not DEBUG` | Keep `True` for the documented HTTPS setup. |
| `DJANGO_SESSION_COOKIE_SECURE` | `not DEBUG` | Keep `True`; session cookies are sent only over HTTPS. |
| `DJANGO_CSRF_COOKIE_SECURE` | `not DEBUG` | Keep `True`; CSRF cookies are sent only over HTTPS. |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | Nonnegative seconds; enable only after HTTPS verification. |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` | Requires an explicit decision covering every subdomain. |
| `DJANGO_SECURE_HSTS_PRELOAD` | `False` | Requires a separate explicit preload decision. |
| `DJANGO_TRUST_X_FORWARDED_PROTO` | `False` | See trusted-proxy requirements below before changing. |
| `DJANGO_DB_ENGINE` | `sqlite` | Set `postgresql`; other values fail startup. |
| `POSTGRES_DB` | None | Required database name when PostgreSQL is selected. |
| `POSTGRES_USER` | None | Required dedicated application role. |
| `POSTGRES_PASSWORD` | None | Required secret; preserved literally, not stripped. |
| `POSTGRES_HOST` | None | Required database host matching its TLS certificate. |
| `POSTGRES_PORT` | `5432` | Integer from 1 to 65535. |
| `DJANGO_DB_SSLMODE` | `verify-full` | Verify database certificate and hostname. |
| `DJANGO_DB_SSLROOTCERT` | Unset | Path to the provider's trusted CA certificate if needed. |
| `DJANGO_DB_CONN_MAX_AGE` | `60` | Nonnegative connection lifetime in seconds; `0` closes after each request. |
| `DJANGO_DB_CONNECT_TIMEOUT` | `10` | Positive connection timeout in seconds. |

Database connection health checks are enabled for PostgreSQL. Each WSGI
thread can hold a connection; size thread/process counts within the database's
connection limit. `DATABASE_URL` is not parsed: use the explicit variables
above, so no URL-parsing dependency or credential escaping is needed.

Production environment example (enter values in the host configuration;
this block is not a shell script):

```dotenv
DJANGO_READ_DOT_ENV=False
DJANGO_SECRET_KEY=<generate-and-store-a-unique-secret>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=detailwise.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://detailwise.example.com

DJANGO_DB_ENGINE=postgresql
POSTGRES_DB=detailwise
POSTGRES_USER=detailwise
POSTGRES_PASSWORD=<application-role-password-from-secret-store>
POSTGRES_HOST=db.example.internal
POSTGRES_PORT=5432
DJANGO_DB_SSLMODE=verify-full
DJANGO_DB_SSLROOTCERT=/run/secrets/postgresql-ca.pem
DJANGO_DB_CONN_MAX_AGE=60
DJANGO_DB_CONNECT_TIMEOUT=10

DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
DJANGO_TRUST_X_FORWARDED_PROTO=False
```

Replace example host names and certificate paths. Same-origin forms normally
do not need an extra CSRF trusted origin when the host and request scheme are
correct; explicit origins are useful for an intentional cross-origin frontend.
Do not add broad origins to work around a broken proxy configuration. Django
host validation and CSRF origin checking serve separate purposes.

## PostgreSQL provisioning and verification

Use a supported, maintained PostgreSQL release compatible with Django 5.2
(PostgreSQL 14 or newer). The pinned Psycopg 3 binary package supports Python
3.13 and avoids requiring a compiler or separate client-library installation.
[Django database support](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes),
[Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).

Provision an empty database and a dedicated role. For a self-managed server,
a provisioning administrator can run the following in `psql`; a managed
provider may supply equivalent controls:

```sql
CREATE ROLE detailwise LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password detailwise
CREATE DATABASE detailwise OWNER detailwise ENCODING 'UTF8' TEMPLATE template0;
```

The `\password` command prompts for the secret instead of embedding it in a
SQL file. Allow this role to connect and create/alter the application's
tables during migrations. Restrict database access to application hosts, use
password authentication and TLS, and arrange backups and restore testing.
Do not give the application a PostgreSQL superuser account.

The default `verify-full` requires a trusted CA and a matching hostname.
Mount the provider CA and set `DJANGO_DB_SSLROOTCERT`, or arrange libpq's
standard trusted-root configuration. The available SSL modes are `disable`,
`allow`, `prefer`, `require`, `verify-ca` and `verify-full`. `require` alone
does not guarantee hostname verification. Only use `disable` for a deliberately
isolated local PostgreSQL experiment; do not weaken the production setting
to bypass certificate failures. See [PostgreSQL TLS verification](https://www.postgresql.org/docs/current/libpq-ssl.html).

After supplying the actual **production PostgreSQL** environment, verify the
selected backend and open a real connection before migrating:

```text
python manage.py check
python manage.py shell -c "from django.db import connection; assert connection.vendor == 'postgresql'; connection.ensure_connection(); print('PostgreSQL connection verified')"
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py showmigrations
python manage.py createsuperuser
```

These are deployment instructions, not commands executed against your local
SQLite database by this change. Migrations create the schema and seed the
three services in the selected PostgreSQL database. They do not copy local
users or bookings. Any later data transfer needs its own reviewed plan and
backup. PostgreSQL integration is not fully verified until a real connection
and migration succeed; configuration tests and `check` alone do not prove it.

## HTTPS, secure cookies and trusted proxies

Terminate public HTTPS at a reverse proxy or the hosting platform, with a
valid certificate for the configured domain. Redirect public HTTP to HTTPS.
Keep secure cookies and Django's HTTPS redirect enabled, and verify login,
POST forms and logout over the real HTTPS URL. Plain HTTP is intentionally
unsuitable for the production cookie settings.

Before trusting **any** forwarded protocol header, verify all of the following:

1. The proxy is under your control or has a documented trusted-header contract.
2. It strips client-supplied `X-Forwarded-Proto` and writes a single value from
   the original request scheme; it sends `https` only for actual HTTPS clients.
3. The application listener is reachable only through that proxy, using a
   loopback/private listener and network access restrictions. Clients cannot
   bypass the proxy and submit spoofed headers directly.
4. The proxy preserves the intended public `Host`, and unknown public hosts
   are rejected at the proxy. Its peer IP and any intermediate proxies are known.

The recommended Waitress command below trusts only the local proxy's
`X-Forwarded-Proto`. Waitress then sets `wsgi.url_scheme`, so leave
`DJANGO_TRUST_X_FORWARDED_PROTO=False`: Django already recognizes HTTPS.
Waitress removes untrusted forwarding headers by default. Do not disable that
protection or use `--trusted-proxy=*` to work around an unknown topology.
[Waitress proxy settings](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html#trusted-proxy).

For another WSGI/proxy arrangement that passes the sanitized header through
without setting the WSGI scheme, explicitly setting
`DJANGO_TRUST_X_FORWARDED_PROTO=True` enables
`SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")`. Django does not
authenticate the header's sender, so the requirements above must already be
satisfied. Incorrect configuration can cause redirect loops or let spoofed
HTTP requests appear secure. See [Django proxy-header requirements](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header).

HSTS is separate from serving HTTPS. Keep `DJANGO_SECURE_HSTS_SECONDS=0`
until HTTPS and certificate renewal work. After verifying the real deployment,
consider a short initial value such as `300`, then increase it deliberately.
Leave `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False` unless all present and
future subdomains must use HTTPS. Leave `DJANGO_SECURE_HSTS_PRELOAD=False`
unless the domain owner explicitly chooses browser preload and has reviewed
its requirements and removal implications. Setting the flag does not itself
submit the domain to a browser preload list.

## Static files and production startup

Install `requirements.txt` in the production Python 3.13 environment. WhiteNoise
runs immediately after Django's `SecurityMiddleware`. With debug disabled,
its compressed manifest storage creates versioned asset names and compression
where beneficial. Local development keeps Django's ordinary static storage.

With the production environment loaded, collect assets before starting or
restarting the WSGI process:

```text
python manage.py collectstatic --noinput
python manage.py check --deploy
waitress-serve --listen=127.0.0.1:8000 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto config.wsgi:application
```

`staticfiles/` is the generated `STATIC_ROOT`, already ignored by Git. Include
it in the release artifact, keep it readable by the WSGI process, and rerun
collection for every changed release. Do not commit it. The source `static/`
directory and Django admin assets are collected automatically. WhiteNoise
serves application assets, not user-uploaded private files.
[WhiteNoise deployment setup](https://whitenoise.readthedocs.io/en/stable/django.html).

The startup command assumes one trusted proxy on the same machine connecting
from `127.0.0.1`; Waitress itself does not terminate TLS. For a separate proxy,
configure the actual peer address, a private bind address and firewall rules
before startup. Run Waitress under a service/process supervisor with restart
and logging support. Do not use `runserver` for production. Set proxy timeouts
and worker/thread capacity with the existing optional 45-second AI request
timeout in mind; capacity and load testing remain deployment work.

## Checks, expected warnings and remaining work

Validation on November 15, 2026 used a project-local `.venv` with Python
3.13.15, Django 5.2.19 and the pinned requirements:

| Validation | Result |
|---|---|
| `python manage.py check` | No issues. |
| `python -m pip check` | No broken requirements. |
| `python manage.py test config --noinput` | All 26 configuration tests passed. |
| `python manage.py test --noinput` | 490 tests discovered: 489 passed, 1 skipped because Node was unavailable. The skipped test launches the optional JavaScript suite. |
| `python manage.py check --deploy`, HSTS `0` | Only `security.W004`. |
| `python manage.py check --deploy`, HSTS `300`, subdomains/preload `False` | Only `security.W005` and `security.W021`. |
| `python manage.py collectstatic --noinput`, debug disabled | 136 static files copied, 408 post-processing results; compressed manifest collection succeeded. |
| WSGI/static smoke checks | Hashed CSS served successfully; local Waitress checks confirmed HTTPS redirection and forwarded-protocol handling for trusted and untrusted peers. |
| PostgreSQL driver/backend import | Psycopg 3.3.9 and Django's PostgreSQL backend loaded; no database connection or migration was attempted. |

The production checks and collection used `DJANGO_READ_DOT_ENV=False`, a
temporary generated secret, example hosts/origins and a PostgreSQL configuration
with dummy credentials and a non-resolving example host. These commands do not
connect to the database. Tests explicitly selected local SQLite configuration;
the local `db.sqlite3` SHA-256 was identical before and after validation. Waitress
smoke checks used loopback HTTP with simulated proxy headers, not real TLS or a
deployment. The generated `.venv/` and `staticfiles/` are ignored by Git.

Run `python manage.py check --deploy` with `DJANGO_DEBUG=False`, a generated
secret, the intended allowed hosts/origins and secure cookie/redirect settings.
For an offline configuration check, the database may remain SQLite: this check
does not migrate it or establish PostgreSQL connectivity. Do not use a real
production database for automated tests.

Expected deliberate warnings, assuming the other production settings above:

| Configuration | Expected warning | Deployment decision |
|---|---|---|
| HSTS seconds `0` | `security.W004` | Verify real HTTPS, then decide when to enable HSTS. |
| Positive HSTS duration with subdomains and preload still `False` | `security.W005`, `security.W021` | Leave these options off until each is explicitly approved for the real domain. |

Warnings are not silenced. Enabling broad HSTS solely to remove a warning is
unsafe. Other warnings, such as weak secrets, debug mode or insecure cookies,
should be resolved before going live. A successful exit from `check --deploy`
can still include warnings; read its output. Django cannot validate DNS,
certificate renewal, proxy sanitization or network access controls for you.
[Django deployment checks](https://docs.djangoproject.com/en/5.2/ref/checks/#security),
[deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

Before public deployment, the operator still needs to choose hosting and the
domain, supply secrets, provision and verify PostgreSQL, run migrations,
collect static files, configure HTTPS and proxy trust, establish backups and
monitoring, and test the actual browser flows. PostgreSQL connection/migration
and real HTTPS infrastructure are not verified by the automated configuration
suite. The existing AI deployment limitations also remain: model reachability,
per-user rate limiting, capacity planning and process-local caching are covered
in [the AI plan](ai_plan.md#14-known-limitations) and are outside this change.
