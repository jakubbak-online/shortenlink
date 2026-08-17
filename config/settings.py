"""
Django settings for config project.
"""

import sys
from pathlib import Path

from decouple import Csv, config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 'test' in sys.argv łapie `manage.py test`; pod pytest-django sys.argv to
# ścieżka do pytest, więc dodatkowo sprawdzamy, czy moduł pytest jest
# w ogóle zaimportowany (jest, zanim pytest-django zdąży załadować te
# ustawienia). Jedna flaga używana niżej w kilku miejscach (Celery eager,
# szybki hasher haseł), żeby nie dublować tego sprawdzenia.
IS_TESTING = "test" in sys.argv or "pytest" in sys.modules


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "django_celery_beat",
    "links",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Zaraz po SecurityMiddleware, przed wszystkim innym - serwuje static/
    # bezpośrednio z procesu gunicorna. Bez tego DEBUG=False (produkcja)
    # zostawia CSS bez obsługi - runserver serwuje statyki tylko sam,
    # w DEBUG=True, czego nie ma na Railway/Fly.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# W kontenerze `db` gada po nazwie usługi z docker-compose, lokalnie (bez
# Dockera) trzeba by podać realny host w .env.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="shortenlink"),
        "USER": config("DB_USER", default="shortenlink"),
        "PASSWORD": config("DB_PASSWORD", default="shortenlink"),
        "HOST": config("DB_HOST", default="db"),
        "PORT": config("DB_PORT", default="5432"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "pl"

TIME_ZONE = "Europe/Warsaw"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# CompressedManifestStaticFilesStorage: collectstatic dogrywa do nazwy
# pliku hash z zawartości (style.abcd1234.css) i od razu gzipuje. Dzięki
# hashowi w nazwie można ustawić far-future cache nagłówki bez ryzyka, że
# przeglądarka pokaże komuś starą wersję CSS-a po deployu.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Analityka kliknięć (links/services.py)

# Sól do haszowania IP przed zapisem w ClickEvent — musi być stała w
# czasie (inaczej ten sam odwiedzający liczy się jako inny po restarcie),
# ale nigdy nie w repo.
IP_SALT = config("IP_SALT")

# Baza MaxMind GeoLite2 (plik .mmdb) do lookupu kraju z IP. Wymaga
# darmowego konta na maxmind.com i osobnego pobrania — nie ma jej w repo.
# Dopóki pliku nie ma na dysku, lookup_country() po prostu zwraca "".
GEOIP_DB_PATH = config("GEOIP_DB_PATH", default=str(BASE_DIR / "geoip" / "GeoLite2-Country.mmdb"))


# Cache (ścieżka przekierowania) i Celery (kolejka zapisu kliknięć) —
# oba na Redisie, ale na osobnych bazach logicznych (0 i 1), żeby np.
# ręczny FLUSHDB na cache nie ruszał kolejki zadań.

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": config("REDIS_URL", default="redis://redis:6379/0"),
    }
}

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://redis:6379/1")
# Zadania odpalone z .delay() to fire-and-forget (widok nie czeka na
# wynik) — nie ma czego przechowywać jako wynik zadania.
CELERY_RESULT_BACKEND = None
CELERY_TIMEZONE = TIME_ZONE

# Testy (manage.py test albo pytest) odpalają zadania Celery synchronicznie,
# w tym samym procesie, zamiast wysyłać je do brokera — inaczej testy
# sprawdzające efekt record_click_task musiałyby czekać na osobno stojącego
# workera. CELERY_TASK_EAGER_PROPAGATES sprawia, że wyjątek z zadania
# wyleci do testu zamiast zniknąć w logu workera.
CELERY_TASK_ALWAYS_EAGER = IS_TESTING
CELERY_TASK_EAGER_PROPAGATES = True

# Produkcyjny hasher (PBKDF2, duża liczba iteracji - to jego zadanie, ma
# być wolny) potrafi kosztować kilka sekund na jedno wywołanie. Testy,
# które hashują hasła (linki z hasłem, tworzenie użytkowników), nie
# potrzebują tej siły - w konfiguracji testowej podmieniamy na szybki,
# niebezpieczny hasher, żeby testy trwały sekundy, a nie minuty.
if IS_TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# django-celery-beat: harmonogram (aggregate_daily_stats, purge_old_events)
# trzymany w bazie, nie w tym pliku - widoczny i edytowalny z poziomu
# panelu admina, bez redeployu przy zmianie godziny czy wyłączeniu zadania.
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"


# API (links/api_views.py) - etap 6. Token auth (nie sesje/ciasteczka -
# to API do skryptowego użytku, nie do przeglądarki), domyślnie każdy
# endpoint wymaga zalogowania (anonimowe tworzenie linków to funkcja
# formularza webowego, nie API - patrz notatki).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "shortenlink API",
    "DESCRIPTION": "Skracacz URL z analityką - zarządzanie linkami i statystyki kliknięć.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
