import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
# Wszystkie ustawienia Celery czytane z settings.py pod prefiksem CELERY_
# (np. CELERY_BROKER_URL -> broker_url) - jedno miejsce na konfigurację
# zamiast osobnego pliku.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
