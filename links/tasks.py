"""Zadania Celery. Cienka warstwa nad services.py - sama logika (zapis
kliknięcia, agregacja, retencja) się nie zmienia, task tylko odbiera ją
z kolejki/harmonogramu i rozpakowuje argumenty."""

from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from links.services import (
    aggregate_daily_stats_for_date,
    purge_old_click_events,
    record_click,
)


@shared_task
def record_click_task(*, link_id: int, ip: str, user_agent: str, referer: str, timestamp: str) -> None:
    # timestamp leci przez kolejkę jako string (JSON nie zna typu
    # datetime) - parsujemy z powrotem tutaj, żeby services.record_click
    # dalej przyjmował zwykły obiekt datetime, tak samo jak wołany
    # bezpośrednio z widoku w etapie 2.
    record_click(
        link_id=link_id,
        ip=ip,
        user_agent=user_agent,
        referer=referer,
        timestamp=parse_datetime(timestamp),
    )


@shared_task
def aggregate_daily_stats() -> None:
    """Harmonogram (django-celery-beat) odpala to raz w nocy - liczy
    DailyStat za wczoraj. Zawsze "wczoraj", nie "dziś": dzień musi się
    już skończyć, inaczej agregat byłby niepełny."""
    yesterday = timezone.now().date() - timedelta(days=1)
    aggregate_daily_stats_for_date(yesterday)


@shared_task
def purge_old_events() -> None:
    purge_old_click_events()
