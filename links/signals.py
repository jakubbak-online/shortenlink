"""Unieważnianie cache'u przekierowań przy zmianie Linku.

Bez tego edycja target_url albo dezaktywacja linku nie miałaby efektu
przez godzinę (TTL cache'u) - użytkownik widziałby stare dane mimo że
w bazie są już nowe."""

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from links.models import Link


@receiver(post_save, sender=Link)
def invalidate_link_cache_on_save(sender, instance, **kwargs):
    cache.delete(f"link:{instance.code}")


@receiver(post_delete, sender=Link)
def invalidate_link_cache_on_delete(sender, instance, **kwargs):
    # Kasujemy też licznik max_clicks - gdyby (teoretycznie) ten sam kod
    # trafił się losowo drugi raz po usunięciu poprzedniego linku, nowy
    # link nie powinien dziedziczyć cudzego licznika kliknięć.
    cache.delete_many([f"link:{instance.code}", f"clicks:{instance.code}"])
