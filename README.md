# shortenlink

[Wersja polska](README.pl.md)

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5-37814A?logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC?logo=pytest&logoColor=white)
[![CI](https://github.com/jakubbak-online/shortenlink/actions/workflows/ci.yml/badge.svg)](https://github.com/jakubbak-online/shortenlink/actions/workflows/ci.yml)

A URL shortener with click analytics. One sentence covers what this
project is actually about: **the redirect has to be instant, and
writing analytics is slow — so the two are decoupled.** The redirect
reads from cache and answers right away; recording the click (parsing
the User-Agent, looking up the country, writing to the database) goes
onto a queue and happens in the background, after the user already has
their response.

## Running it

```bash
cp .env.example .env      # fill in SECRET_KEY / IP_SALT
docker compose up
```

That's it. Migrations and `collectstatic` run automatically on startup
(`entrypoint.sh`). The app is served at `http://localhost:8000/`.

## How it works (the redirect path)

```
                    GET /<code>/
browser       ─────────────────────▶  Django (gunicorn)
                                            │
                              cache hit     │     cache miss
                        (Redis: link:<code>)│  (Postgres, then written to cache)
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                          link data                SELECT from Postgres
                              │                           │
                              └─────────────┬─────────────┘
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

## Design decisions

**Recording a click is asynchronous.** A Postgres insert, User-Agent
parsing, and a geolocation lookup add up to a dozen-odd milliseconds
tacked onto *every* redirect — and nobody looks at the dashboard in the
same second someone clicked. The view enqueues a Celery task and
returns `302` immediately; all the slow work happens in the worker,
after the response. Cost: if the worker happens to be down, redirects
keep working without interruption, but individual clicks from that
window never get recorded — accepted deliberately, this is analytics,
not financial records.

**`302`, not `301`.** A permanent redirect gets cached by the browser
for good, so it stops asking the server on later visits — analytics
stop counting, and a changed target URL never reaches people who
already clicked once. `302` forces a request every single time, at the
cost of every click being a real request instead of the browser's
local memory.

**Code collisions handled via `IntegrityError`, not `exists()`.**
Checking "is this code free" and then writing is a classic race — two
concurrent requests can both see the same free code and both try to
claim it. The only thing that can resolve that atomically is a unique
index in the database: the code tries to write, catches the exception
on collision, and retries (up to 5 times — in practice almost never
needed more than once across 62⁶ possible codes).

**`DailyStat` as deliberate denormalization.** A 30-90 day chart
computed from raw `ClickEvent` rows on every dashboard visit means
scanning and grouping a growing number of rows. A nightly Celery Beat
job computes it once and stores a handful of aggregated rows instead.
Bonus: those rows survive the raw-event retention window (90 days), so
historical numbers stick around even after the source events are long
gone.

**Hashed IPs instead of raw addresses.** GDPR treats an IP address as
personal data. For counting unique visits per day, a salted hash (the
salt lives in an environment variable, not in the repo) is more than
enough, without storing anything that identifies a person.

One more deliberate departure from the obvious schema: `Link.owner` is
**nullable** — creating a link anonymously is an intended feature (with
its own, lower rate limit), not an oversight.

## Benchmark results

Methodology: [Locust](https://locust.io) (`benchmarks/locustfile.py`),
scenario "50 users hammering the same short link for a minute", median
and 95th-percentile response time.

The stage-2 version (recording clicks **synchronously**, inside the
view, no cache) was measured locally on SQLite, before the Docker
environment was ready — and the signal is clear even so: the median
looks harmless (150 ms), but the 95th percentile reaches several
**seconds**, because the tail of the distribution degrades under load
well before the mean shows anything. A formal, apples-to-apples
before/after measurement on the target stack (Postgres + Redis + Celery
in Docker, not SQLite) is in progress — SQLite has a different locking
model under concurrent writes than Postgres, so it isn't a trustworthy
baseline for the final numbers.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

In the container: `docker compose exec web pytest`. The test
configuration runs Celery tasks synchronously
(`CELERY_TASK_ALWAYS_EAGER`) and swaps in a fast password hasher
instead of the production PBKDF2 one — a test doesn't need to be as
computationally expensive as a real login.

Lint: `ruff check .` and `ruff format --check .` (also run in CI on
every push, alongside pytest, against Postgres and Redis service
containers).
