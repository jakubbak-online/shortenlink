"""Zadania Celery. Cienka warstwa nad services.py - sama logika zapisu
kliknięcia (record_click) się nie zmienia, task tylko odbiera ją z
kolejki i rozpakowuje argumenty."""

from celery import shared_task
from django.utils.dateparse import parse_datetime

from links.services import record_click


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
