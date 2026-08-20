# skroclinka.pl

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5-37814A?logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![DRF](https://img.shields.io/badge/Django%20REST-Framework-A30000?logo=django&logoColor=white)
![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC?logo=pytest&logoColor=white)
[![CI](https://github.com/jakubbak-online/skroclinka.pl/actions/workflows/ci.yml/badge.svg)](https://github.com/jakubbak-online/skroclinka.pl/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

*Polska wersja: [README.pl.md](README.pl.md)*

**Live**: [skroclinka.pl](https://skroclinka.pl)

A URL shortener with click analytics. One sentence covers what this
project is actually about: **the redirect has to be instant, and
writing analytics is slow, so the two are decoupled.** The redirect
reads from cache and answers right away; recording the click (parsing
the User-Agent, hashing the IP, resolving the country, writing to the
database) goes onto a queue and happens in the background, after the
user already has their response.

Built solo as a portfolio project to practice a specific problem end to
end (the hot-path-vs-slow-write split), not to demonstrate a checklist
of Django features. Every design decision below exists to answer "why",
not just "what", including the ones that turned out to be wrong on the
first attempt and got caught by a test or a real deploy.

## Table of Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Local Configuration](#local-configuration)
- [Getting Started](#getting-started)
- [Feature Walkthrough](#feature-walkthrough)
- [Testing](#testing)
- [API Reference](#api-reference)
- [Component Deep Dive](#component-deep-dive)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)
- [Roadmap](#roadmap)
- [Author & License](#author--license)

## Highlights

- **Instant redirects under load, verified by measurement.** The
  synchronous, pre-cache version of the redirect view was benchmarked
  with Locust before it was replaced; the async, cached version is
  benchmarked the same way afterward, so "faster" is a number, not a
  claim. See [Testing](#testing) and the benchmark note there.
- **Race conditions handled at the database, not in application logic.**
  Short-code collisions are resolved by catching `IntegrityError` from a
  unique index and retrying, each attempt wrapped in its own
  `transaction.atomic()` savepoint, not by checking `exists()` first
  (a check-then-write race under concurrent requests).
- **A denormalized aggregate table, not a bigger cache.** `DailyStat` is
  computed once a night by Celery Beat from raw `ClickEvent` rows and
  outlives them; the 90-day raw-event retention job can delete millions
  of rows without losing a single day of historical chart data.
- **GDPR-aware by construction.** IP addresses are never stored raw,
  only a salted SHA-256 hash, enough to count unique visits per day
  without identifying anyone. Raw click events are purged after 90 days;
  the aggregates that outlive them contain no personal data at all.
- **A real deployment, not a `runserver` screenshot.** Five Docker
  services (Postgres, Redis, Django/gunicorn, a Celery worker, Celery
  Beat) plus Caddy as a reverse proxy, running on a DigitalOcean droplet
  with automatic HTTPS from Let's Encrypt and CD from GitHub Actions on
  every push to `main`.
- **404, not 403, for other people's links.** The API's queryset is
  filtered to the requesting user before lookup, so someone else's link
  simply doesn't exist as far as the endpoint is concerned, no
  information leak about whether the code is taken.
- **Every bug below is a real one**, not a hypothetical. The
  [Troubleshooting](#troubleshooting) section is a log of things that
  actually broke during development and how each one was found.

## Architecture

```
                    GET /<code>/
browser       ─────────────────────▶  Caddy (HTTPS, Let's Encrypt)  ──▶  Django (gunicorn)
                                                                              │
                                                            cache hit         │        cache miss
                                                      (Redis: link:<code>)   │   (Postgres, then written to cache)
                                                            ┌─────────────────┴─────────────────┐
                                                            ▼                                     ▼
                                                        link data                         SELECT from Postgres
                                                            │                                     │
                                                            └─────────────────┬───────────────────┘
                                                                              ▼
                                                is_active? / expires_at? / password? / max_clicks?
                                                          (limit tracked via Redis INCR,
                                                           not COUNT(*) on events)
                                                                              │
                                                                              ▼
                                                            302 → target_url  ◀── browser gets this RIGHT AWAY
                                                                              │
                                                                              ┆  (in the background, after the response)
                                                                              ▼
                                                                  Celery worker: parses the User-Agent,
                                                                  hashes the IP, resolves the country,
                                                                  writes ClickEvent to Postgres
                                                                              │
                                                          every night, Celery beat ▼
                                                          aggregates yesterday's ClickEvents → DailyStat
                                                          (the dashboard reads from here, not raw events)
                                                          and purges events older than 90 days
```

A full step-by-step walkthrough of every piece in this diagram is in
[Component Deep Dive](#component-deep-dive).

## Tech Stack

| Technology | Used for |
|---|---|
| **Django 6.0 / Python 3.13** | The application itself, split into a thin view layer and a `services.py` business-logic layer that both the views and the REST API call into |
| **PostgreSQL 16** | Durable storage for links, click events, and daily aggregates |
| **Redis 7** | Three roles on two logical databases: redirect cache + rate-limit counters (DB 0), Celery broker (DB 1), kept apart so a manual `FLUSHDB` on one doesn't touch the other |
| **Celery + Celery Beat** | Async click recording, plus two nightly scheduled jobs (aggregation, retention), scheduled from a database table via `django-celery-beat` so the schedule is editable from the admin without a redeploy |
| **Django REST Framework + drf-spectacular** | Token-authenticated CRUD API for links, with an auto-generated OpenAPI schema at `/api/docs/` |
| **Docker Compose** | Two topologies: a dev one with bind mounts and directly-exposed ports, a production one with no bind mounts, no exposed DB/Redis ports, and Caddy as the only entry point |
| **Caddy 2** | Reverse proxy with fully automatic HTTPS (Let's Encrypt, including renewal) driven by a single `DOMAIN` environment variable |
| **gunicorn + WhiteNoise** | Production WSGI server and compressed, cache-busted static file serving, no separate nginx/CDN needed |
| **pytest + pytest-django** | 80 tests, migrated mid-project from `manage.py test` (see [Troubleshooting](#troubleshooting)) |
| **ruff** | Linting and formatting, enforced in CI |
| **GitHub Actions** | CI (ruff + pytest against real Postgres/Redis service containers) and CD (SSH deploy to the droplet, gated on CI passing and only on pushes to `main`) |
| **Locust** | Load-testing the redirect path to produce actual before/after numbers, not estimates |

## Project Structure

```
skroclinka.pl/
├── config/                   Django project settings, root URLconf, Celery app
├── links/
│   ├── models.py              Link, ClickEvent, DailyStat
│   ├── services.py            business logic: code generation, collision handling,
│   │                          IP hashing, device classification, aggregation, retention
│   ├── views.py                the redirect path (the hot path) + the create-link form
│   ├── tasks.py                thin Celery wrappers around services.py
│   ├── ratelimit.py            Redis-based fixed-window rate limiter (own implementation)
│   ├── signals.py              cache invalidation on Link save/delete
│   ├── forms.py                the web form (target URL + collapsible advanced settings)
│   ├── api_views.py / serializers.py / api_urls.py   the REST API
│   ├── admin.py                Django admin registration for all three models
│   ├── templates/links/        server-rendered HTML, dark-mode-by-default, no JS framework
│   └── tests/                  80 tests across 7 files, one per concern
├── benchmarks/locustfile.py    load-test scenario used for the before/after measurement
├── scripts/gen_prod_env.sh     generates a production .env from .env.example on the server
├── docker-compose.yml          dev stack: bind mounts, ports exposed for local debugging
├── docker-compose.prod.yml     prod stack: no bind mounts, Caddy as the only public entry point
├── Caddyfile                   reverse proxy + automatic HTTPS config
├── Dockerfile / entrypoint.sh  application image + container entrypoint
├── .github/workflows/ci.yml    CI (lint + test) and CD (SSH deploy) pipeline
├── requirements.txt / requirements-dev.txt   runtime deps / +lint+test tooling, kept separate
│                                             so the production image doesn't ship pytest/ruff
├── README.md / README.pl.md
└── LICENSE                     MIT
```

## Local Configuration

The repository ships no real secrets. Copy `.env.example` to `.env` and
fill in the two values that matter for local development:

1. **`SECRET_KEY`**: Django's cryptographic signing key. Generate one
   with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
   Avoid `$` in the value: Docker Compose performs its own `${VAR}`
   interpolation over `.env` files, and a literal `$` in a value gets
   silently reinterpreted (see [Troubleshooting](#troubleshooting)).
2. **`IP_SALT`**: the salt mixed into every hashed IP address before
   it's stored. Generate with
   `python -c "import secrets; print(secrets.token_hex(32))"`. Must stay
   constant over time (rotating it makes the same visitor look like a
   new one), and must never be committed.

Everything else in `.env.example` already has a working default for
local Docker use (`DB_HOST=db`, `REDIS_URL=redis://redis:6379/0`, etc.)
and doesn't need to change to get the stack running. `DOMAIN` and
`GEOIP_DB_PATH` are optional; see the comments in `.env.example` for
what each one unlocks.

**On a server**, `scripts/gen_prod_env.sh <host-or-domain>` generates a
complete production `.env` in one command (random `SECRET_KEY` and
`IP_SALT`, `DEBUG=False`, `ALLOWED_HOSTS` set to whatever you pass it).

## Getting Started

**Requirements:** Docker + Docker Compose. Nothing else, no local
Python install needed.

```bash
git clone https://github.com/jakubbak-online/skroclinka.pl.git
cd skroclinka.pl
cp .env.example .env      # fill in SECRET_KEY and IP_SALT, see above
docker compose up
```

That single command builds the app image, starts Postgres and Redis,
runs migrations and `collectstatic` in a one-shot `migrate` service
(so `web`/`worker`/`beat` only start once the schema actually exists,
see [Troubleshooting](#troubleshooting) for why that's a dedicated
service and not just a startup script), and starts the web server,
Celery worker, and Celery Beat. The app is served at
`http://localhost:8000/`.

Optional: `docker compose exec web python manage.py createsuperuser`
for admin access at `/admin/`.

`docker-compose.prod.yml` is the production topology used on the live
deployment: no bind mounts (code is baked into the image at build
time), no directly-exposed Postgres/Redis ports, and Caddy in front
handling HTTPS. It isn't meant to be run locally without a real domain,
Let's Encrypt needs to verify domain ownership with a live HTTP request.

## Feature Walkthrough

Open `http://localhost:8000/` (or [skroclinka.pl](https://skroclinka.pl)):

1. **Paste a URL, get a short one.** Just the address field and a
   submit button by default.
2. **Expand "Advanced settings"** for the rest: a custom code instead of
   a random one, an optional password, an expiration date, a click
   limit. All optional, all collapsed by default because most links
   don't need any of them.
3. **Click the short link.** It redirects immediately (`302`). If it has
   a password, you'll see a small form first; a correct password
   redirects the same way a plain link would, an incorrect one doesn't
   count toward the click limit or the analytics.
4. **Open `/<code>/stats/`** (linked right under the short link after
   creating it) for the dashboard: total clicks, a daily chart (from
   `DailyStat`, not a live query over raw events), and a table of the
   most recent individual clicks with device/browser/OS/referrer.
5. **Toggle light/dark** in the top-right corner of any page. Dark is
   the default; the choice persists in `localStorage`.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

In the container: `docker compose exec web pytest`. The test
configuration runs Celery tasks synchronously
(`CELERY_TASK_ALWAYS_EAGER`) and swaps in a fast, insecure password
hasher and a non-manifest static storage instead of the production ones
(see [Troubleshooting](#troubleshooting) for why the latter is
necessary, not just an optimization).

80 tests across 7 files, each one chosen for what it actually verifies:
short-code collision handling (including a mocked forced collision),
every redirect branch (cache hit/miss, expired, inactive, password,
click-limit), cache invalidation on edit, rate-limit thresholds and
window resets (via `freezegun`, not `time.sleep()`), daily aggregation
on 300 deliberately-dated events including a day-boundary edge case,
retention's effect on historical totals, and cross-user isolation in
the API.

Lint: `ruff check .` and `ruff format --check .`. Both run in CI on
every push, alongside pytest, against real Postgres and Redis service
containers, not mocks.

**Benchmark methodology and results:** [Locust](https://locust.io)
(`benchmarks/locustfile.py`), scenario "50 users hammering the same
short link for a minute", median and 95th-percentile response time. The
pre-cache, synchronous version was measured locally on SQLite before
the Docker environment was ready; the signal was clear even so, median
looked harmless (150 ms) but the 95th percentile reached several
**seconds**, because the tail of the distribution degrades under load
well before the mean shows anything. Formal, apples-to-apples numbers
on the real production stack (Postgres + Redis + Celery, not SQLite,
which has a different concurrent-write locking model) are the next
thing on the [Roadmap](#roadmap).

## API Reference

Full interactive schema at [`/api/docs/`](https://skroclinka.pl/api/docs/)
(Swagger UI, drf-spectacular). Summary:

```
POST   /api/auth/token/         {username, password} -> {token}
GET    /api/links/              list your own links, paginated
POST   /api/links/               create a link
GET    /api/links/{code}/        details
PATCH  /api/links/{code}/        edit
DELETE /api/links/{code}/        delete
GET    /api/links/{code}/stats/  click count + recent events
```

Token auth: `Authorization: Token <token>` on every request after
obtaining one. Every endpoint requires authentication (anonymous link
creation is a feature of the web form, not the API, see
[Component Deep Dive](#component-deep-dive)). A link that exists but
belongs to another user returns `404`, matching the behavior of a link
that was never created, not `403`, which would confirm the code is
taken.

## Component Deep Dive

<details>
<summary><strong>Expand for a component-by-component walkthrough with source links</strong></summary>

### 1. Models ([`links/models.py`](links/models.py))

- **`Link`**: `owner` (nullable, anonymous link creation is intentional,
  see below), `code` (unique, indexed), `target_url`, `title`,
  `is_active`, `expires_at`, `max_clicks`, `password_hash`,
  `created_at`. Indexed on `(owner, -created_at)` for the "my links"
  list.
- **`ClickEvent`**: one row per recorded click, `ip_hash` (never a raw
  IP), `country`, `referer_domain`, `device_type`
  (desktop/mobile/tablet/**bot**), `browser`, `os`. Indexed on
  `(link, -created_at)`.
- **`DailyStat`**: `link`, `date`, `clicks`, `unique_visitors`, a unique
  constraint on `(link, date)` so `update_or_create` can be idempotent.

`Link.owner` is deliberately nullable, a departure from the schema this
project started from. The rate-limiting design explicitly distinguishes
"create a link (logged in)" from "create a link (anonymous)" with two
different thresholds, so anonymous link creation has to actually work,
not just be permitted by accident.

### 2. Business logic ([`links/services.py`](links/services.py))

Everything that isn't HTTP-specific lives here, so it's testable
without a client and reusable from both the web view and the REST API
without duplication.

- **`create_link()`**: generates a random 6-character base62 code (62⁶ ≈
  56 billion combinations) or accepts a custom one. Collisions aren't
  prevented by checking `exists()` first, that's a check-then-write
  race between concurrent requests, they're handled by attempting the
  write and catching `IntegrityError` from the unique index, the only
  thing that can resolve it atomically. Each attempt is wrapped in its
  own `transaction.atomic()` savepoint; without that, a caught
  `IntegrityError` leaves the *entire* surrounding transaction unusable
  until it's rolled back, not just that one attempt, a bug this
  project's own test suite caught (see [Testing](#testing)).
- **`hash_ip()`**: `SHA-256(ip + IP_SALT)`. The salt lives in an
  environment variable specifically so a leaked database dump alone
  isn't enough to build a rainbow table against it.
- **`classify_device()`**: bots get their own category instead of being
  dropped or counted as "desktop", crawler traffic can outnumber real
  visitors and would otherwise silently distort every chart.
- **`aggregate_daily_stats_for_date()`**: one `GROUP BY link_id` query
  per day covering every link at once (not a loop per link), excluding
  bots, written with `update_or_create` so re-running it for a day
  overwrites rather than duplicates.
- **`link_total_clicks()`**: sums `DailyStat.clicks` (survives
  retention) plus today's not-yet-aggregated `ClickEvent` rows, not a
  plain `ClickEvent.objects.filter(link=link).count()`, which would
  quietly under-report once the 90-day purge starts deleting rows.

### 3. Views ([`links/views.py`](links/views.py))

- **`redirect_view`**: the one endpoint the whole project exists to
  make fast. Rate limit check, then cache lookup (`link:{code}`),
  Postgres only on a miss, then `is_active`/`expires_at`/password/
  `max_clicks` checks against the cached data, then `record_click_task
  .delay()` (non-blocking), then `HttpResponseRedirect`, which Django
  returns as `302` by default. `302`, not `301`: a permanent redirect
  gets cached by the browser for good, so it stops asking the server on
  later visits, analytics stop counting and a changed target URL never
  reaches people who already clicked once.
- **`create_link_view`**: renders the form, rate-limited separately by
  user (if authenticated) or IP (if not) at a lower threshold.
- **`stats_view`**: reads from `DailyStat` for the chart, from raw
  `ClickEvent` only for the "most recent clicks" table, the one place
  where a live view over raw events is actually the right call.

### 4. Tasks ([`links/tasks.py`](links/tasks.py))

Thin `@shared_task` wrappers around `services.py` functions, nothing
else. `record_click_task` re-parses the timestamp (Celery serializes
task arguments to JSON, which has no datetime type) and calls
`services.record_click()`; `aggregate_daily_stats` and
`purge_old_events` are the two nightly jobs Celery Beat runs on a
schedule stored in the database (`django-celery-beat`), editable from
the Django admin without a redeploy.

### 5. Rate limiting ([`links/ratelimit.py`](links/ratelimit.py))

A ~15-line own implementation on Redis (`INCR` + `EXPIRE`, fixed
window), not a library, specifically to demonstrate understanding the
mechanism rather than configuring someone else's. Thresholds: 3
links/hour anonymous, 20/hour authenticated, 300 redirects/minute per
IP, `429` with `Retry-After` on all of them. Fixed windows have a known
weakness (up to ~2x the limit right at a window boundary); acceptable
here because the goal is stopping bulk link generation and code
scanning, not defending against a precisely-timed attack. A sliding
window or token bucket would close that gap at the cost of a sorted-set
structure in Redis instead of a single counter.

### 6. Cache invalidation ([`links/signals.py`](links/signals.py))

`post_save`/`post_delete` signals on `Link` clear its cache entry.
Chosen over an explicit call from `services.py` specifically because it
also fires on edits made from the Django admin or a shell, which the
service layer never sees.

### 7. REST API ([`links/api_views.py`](links/api_views.py), [`links/serializers.py`](links/serializers.py))

A `ModelViewSet` whose `get_queryset()` filters to
`Link.objects.filter(owner=request.user)` before anything else runs, so
DRF's own `get_object()` simply can't find another user's link, no
custom permission-denied logic needed, and the `404` it returns doesn't
leak whether the code exists at all. The serializer always calls
`services.create_link()` rather than `Link.objects.create()` directly,
so the API gets the same collision retry and reserved-word validation
as the web form for free.

### 8. Deployment (`Dockerfile`, `entrypoint.sh`, `docker-compose*.yml`, `Caddyfile`)

- **`entrypoint.sh`** is deliberately trivial (`exec "$@"`), all
  migration/collectstatic logic lives in a dedicated one-shot `migrate`
  service that `web`/`worker`/`beat` wait on via `depends_on: {condition:
  service_completed_successfully}`, see [Troubleshooting](#troubleshooting)
  for the bug that motivated pulling this out of a per-service startup flag.
- **`docker-compose.prod.yml`** has no bind mounts (the image is
  rebuilt and code is copied in at deploy time, not live-mounted from
  the host) and no host ports on `db`/`redis`, Caddy is the only
  process listening on 80/443.
- **`Caddyfile`** reads a single `DOMAIN` environment variable and
  handles the rest: certificate issuance, renewal, and an HTTP→HTTPS
  redirect for the `www` subdomain, no manual `certbot` step.

</details>

## Troubleshooting

<details>
<summary><strong>Expand for real bugs found during development and how each one was diagnosed</strong></summary>

These aren't hypothetical "gotchas", every one of these actually
happened while building this project and is here in case the same
class of bug shows up again.

**A collision retry that worked by hand but broke under test.** The
first version of `create_link()` caught `IntegrityError` on a code
collision and just retried. It worked fine when clicked through
manually. A test that forced a collision via mocking `generate_code()`
failed with `TransactionManagementError` on the *second* attempt: an
uncaught `IntegrityError` leaves the whole surrounding transaction
unusable until it's rolled back, not just the failed statement. Fix:
wrap each attempt in its own `transaction.atomic()` savepoint, so a
collision only unwinds that one attempt.

**`beat` crash-looping with `relation "django_celery_beat_..." does
not exist`.** Only the `web` service ran migrations on startup, gated
behind an environment flag; `worker` and `beat` started in parallel
with no guarantee the schema existed yet, and `depends_on: {condition:
service_healthy}` on Postgres only proves *Postgres* is up, not that
Django's migrations have run. Fix: migrations became their own
one-shot `migrate` service that everything else waits on with
`condition: service_completed_successfully`, the standard
"run-once-before-everything-else" Compose pattern.

**Every page returning `500` in production, but not locally.**
`docker-compose.prod.yml` deliberately has no bind mounts, so `migrate`
and `web` are separate containers with independent, ephemeral
filesystems. `collectstatic` (run inside `migrate`) wrote its manifest
into a filesystem that `web` never saw, so `CompressedManifestStaticFilesStorage`
had no manifest to look up, and *every* `{% static %}` tag in the base
template raised `ValueError`. Fix: a named Docker volume
(`staticfiles:`) shared between `migrate` and `web`.

**CI failing on "Install dependencies", before ruff or pytest even
ran.** `django-celery-beat==2.9.0` requires `Django<6.1`; the project
had `Django==6.1` pinned. It worked in the long-lived local venv
(already-installed packages don't get fully re-validated) but not in
CI's fresh install. A second, related bug was hiding behind the first:
`CompressedManifestStaticFilesStorage` requires `collectstatic` to have
already run, which nothing does before `pytest`, so every test touching
a template would have failed too. Fix: pin `Django==6.0.8`, and use a
plain `StaticFilesStorage` (no manifest) specifically under
`IS_TESTING`. Both were found locally, in a fresh venv, before the next
push, not from a second failed-CI email.

**`docker compose up` failing on `docker-credential-desktop:
executable file not found in %PATH%`, only in one terminal.** Turned out
to be specific to the Git Bash environment being used, PowerShell on
the exact same machine had Docker and its credential helper on `PATH`
with no changes needed. Worth remembering on Windows: a tool "not
working" can mean the shell, not the tool.

**Docker Compose silently mangling a value from `.env`.** A generated
`SECRET_KEY` happened to contain a `$`. Compose performs its own
`${VAR}` interpolation over `.env` files (not just over
`docker-compose.yml` itself), so `$xyz` inside a value gets read as "the
value of environment variable `xyz`", producing a `"xyz" variable is not
set` warning and a silently truncated secret. Fix: regenerate without
special characters (`secrets.token_urlsafe`, alphanumeric plus `-`/`_`
only).

</details>

## Security Considerations

| Threat | Vector | Risk | Mitigation in this project |
|---|---|---|---|
| Open redirect / phishing | Anyone can point a short link at any URL | Medium | Not currently mitigated beyond `URLField` validation; see [Roadmap](#roadmap) for a planned Safe Browsing check |
| IP address exposure | Click analytics inherently see visitor IPs | High if mishandled | Never stored raw, only a salted SHA-256 hash (salt in an environment variable, not the repo); raw click events are purged after 90 days |
| Enumerating other users' links via the API | Guessing another user's link code | Low | Queryset filtered to `request.user` before lookup, so a foreign link returns `404`, not `403`, no confirmation the code is taken |
| Mass link creation / spam | No CAPTCHA on the public form | Medium | Rate-limited (3/hour anonymous, 20/hour authenticated) |
| Password-protected link brute-forcing | No dedicated lockout on password attempts | Medium | Covered generically by the redirect endpoint's per-IP rate limit (300/min), not a dedicated per-link lockout |
| Secret sprawl | `SECRET_KEY`, `IP_SALT`, DB credentials live in `.env` | High if leaked | `.env` is gitignored everywhere; production values are generated on the server itself (`scripts/gen_prod_env.sh`), never committed or transmitted |
| Database/cache exposed to the internet | Docker port mapping | High if exposed | Dev compose exposes Postgres/Redis on the host for local debugging; `docker-compose.prod.yml` exposes neither, only Caddy listens on 80/443 |

## Roadmap

Deliberately left for later, none of it blocked shipping a working,
deployed, end-to-end pipeline:

- **Real before/after benchmark numbers** on the production stack
  (Postgres + Redis + Celery), replacing the current SQLite-measured
  preliminary ones now that the full stack is actually deployable.
- **`DailyStat` vs. raw-`ClickEvent` query time**, measured side by
  side on real data, the comparison the aggregation table's design
  argument rests on.
- **MaxMind GeoLite2 database** on the server; `lookup_country()` is
  already written and gracefully returns an empty string without it,
  country data just doesn't populate until the `.mmdb` file (which
  needs a free MaxMind account) is in place.
- **Open-redirect mitigation**: a Google Safe Browsing check against
  `target_url` before a link goes live, plus an interstitial warning
  page for links flagged as suspicious.
- **Sliding-window or token-bucket rate limiting**, closing the
  boundary-burst gap the current fixed-window implementation
  deliberately accepts.
- **Buffered click writes**: one Celery task per click is simple and
  currently sufficient; batching writes in Redis and flushing every few
  seconds would be the first thing to change under materially higher
  traffic.
- **Dashboard screenshot** in this README, straightforward now that the
  app is actually live.

## Author & License

Built by [Jakub Bąk](https://github.com/jakubbak-online).

Licensed under the [MIT License](LICENSE).
