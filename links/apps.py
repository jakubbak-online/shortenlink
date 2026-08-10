from django.apps import AppConfig


class LinksConfig(AppConfig):
    name = 'links'

    def ready(self):
        from links import signals  # noqa: F401
