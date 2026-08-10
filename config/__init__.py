# Import przy starcie Django, żeby dekorator @shared_task w każdej
# aplikacji od razu widział tę instancję Celery.
from config.celery import app as celery_app

__all__ = ("celery_app",)
