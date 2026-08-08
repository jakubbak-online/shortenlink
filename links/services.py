"""Logika biznesowa aplikacji links.

Widoki (i później serializery API oraz zadania Celery) mają tylko wołać
te funkcje, nie duplikować logiki. Dzięki temu da się to przetestować bez
klienta HTTP — i dzięki temu, że nic tu nie dotyka obiektu `request`,
można to samo bez zmian wywołać z zadania w tle.
"""

import hashlib
import secrets
from functools import lru_cache
from urllib.parse import urlparse

import user_agents
from django.conf import settings
from django.db import IntegrityError, transaction
from geoip2.database import Reader
from geoip2.errors import AddressNotFoundError

from links.models import ClickEvent, Link

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
CODE_LENGTH = 6
MAX_GENERATE_ATTEMPTS = 5

# Słowa, których nie może zająć wygenerowany ani (później) własny kod —
# kolidowałyby z resztą routingu (/admin/, /api/...). Na razie egzekwowane
# tylko przy generowaniu losowym; przy własnych kodach (etap 4) dojdzie
# walidacja formularza korzystająca z tej samej stałej.
RESERVED_CODES = {
    "admin", "api", "static", "media",
    "login", "logout", "register", "docs",
}


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def create_link(*, owner, target_url: str, **kwargs) -> Link:
    """Tworzy Link z losowym, unikalnym kodem.

    Nie sprawdzamy najpierw, czy kod jest wolny — dwa równoległe żądania
    mogłyby zobaczyć ten sam wolny kod. Zamiast tego próbujemy zapisać i
    reagujemy na IntegrityError z unikalnego indeksu, które jedyne potrafi
    to rozstrzygnąć atomowo.
    """
    for _ in range(MAX_GENERATE_ATTEMPTS):
        code = generate_code()
        if code.lower() in RESERVED_CODES:
            continue
        try:
            # atomic() daje savepoint na próbę — bez tego IntegrityError
            # zostawia całą otaczającą transakcję w stanie zepsutym i
            # kolejne zapytanie (choćby następna próba) wybucha
            # TransactionManagementError zamiast po prostu spróbować dalej.
            with transaction.atomic():
                return Link.objects.create(
                    owner=owner,
                    target_url=target_url,
                    code=code,
                    **kwargs,
                )
        except IntegrityError:
            continue
    raise RuntimeError("Nie udało się wygenerować unikalnego kodu")


def hash_ip(ip: str) -> str:
    """RODO traktuje IP jako dane osobowe — do liczenia unikalnych wejść
    wystarczy hash z solą, więc surowego adresu nigdy nie zapisujemy.
    Sól (IP_SALT) siedzi w .env, nie w repo."""
    return hashlib.sha256((ip + settings.IP_SALT).encode()).hexdigest()


def _device_type(ua) -> str:
    """Boty do osobnej kategorii, nie do kosza i nie razem z ludźmi —
    crawlery potrafią wygenerować więcej wejść niż realni użytkownicy i
    zniekształciłyby statystyki, gdyby wpadały do "desktop"."""
    if ua.is_bot:
        return "bot"
    if ua.is_mobile:
        return "mobile"
    if ua.is_tablet:
        return "tablet"
    return "desktop"


def classify_device(user_agent_string: str) -> str:
    return _device_type(user_agents.parse(user_agent_string))


@lru_cache(maxsize=1)
def _geoip_reader() -> Reader | None:
    # Baza GeoLite2 wymaga darmowego konta MaxMind i nie jest w repo (patrz
    # private/notatki.md) — dopóki jej nie ma na dysku, geolokalizacja po
    # prostu nic nie zwraca zamiast wywalać całe przekierowanie.
    try:
        return Reader(settings.GEOIP_DB_PATH)
    except FileNotFoundError:
        return None


def lookup_country(ip: str) -> str:
    reader = _geoip_reader()
    if reader is None or not ip:
        return ""
    try:
        return reader.country(ip).country.iso_code or ""
    except (AddressNotFoundError, ValueError):
        return ""


def record_click(*, link_id: int, ip: str, user_agent: str, referer: str, timestamp) -> ClickEvent:
    """Cała 'wolna' robota przy kliknięciu: parsowanie User-Agenta, hash
    IP, lookup kraju, insert do bazy.

    Etap 2 woła to wprost z widoku (synchronicznie — stąd benchmark
    'przed'). Etap 3 przenosi wywołanie do zadania Celery, bez zmiany
    ani jednej linijki tutaj — funkcja od początku nie przyjmuje obiektu
    `request`, tylko proste typy, żeby to przeniesienie było bezbolesne.
    """
    ua = user_agents.parse(user_agent)

    return ClickEvent.objects.create(
        link_id=link_id,
        created_at=timestamp,
        ip_hash=hash_ip(ip),
        country=lookup_country(ip),
        referer_domain=urlparse(referer).netloc if referer else "",
        device_type=_device_type(ua),
        browser=ua.browser.family,
        os=ua.os.family,
    )
