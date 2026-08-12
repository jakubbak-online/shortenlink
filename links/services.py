"""Logika biznesowa aplikacji links.

Widoki (i później serializery API oraz zadania Celery) mają tylko wołać
te funkcje, nie duplikować logiki. Dzięki temu da się to przetestować bez
klienta HTTP — i dzięki temu, że nic tu nie dotyka obiektu `request`,
można to samo bez zmian wywołać z zadania w tle.
"""

import hashlib
import re
import secrets
from functools import lru_cache
from urllib.parse import urlparse

import user_agents
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from geoip2.database import Reader
from geoip2.errors import AddressNotFoundError

from links.models import ClickEvent, Link

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
CODE_LENGTH = 6
MAX_GENERATE_ATTEMPTS = 5

# Słowa, których nie może zająć wygenerowany ani własny kod — kolidowałyby
# z resztą routingu (/admin/, /api/...).
RESERVED_CODES = {
    "admin", "api", "static", "media",
    "login", "logout", "register", "docs",
}

# Własny kod jest luźniejszy niż losowy (dopuszcza myślnik/podkreślnik,
# zmienną długość — to ma być coś zapamiętywalnego typu "moja-promocja"),
# ale wciąż ograniczony do max_length pola Link.code (16 znaków).
CUSTOM_CODE_MIN_LENGTH = 3
CUSTOM_CODE_MAX_LENGTH = 16
CUSTOM_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def validate_custom_code(code: str) -> None:
    """Rzuca ValueError, jeśli kod się nie nadaje na własny — format albo
    zastrzeżone słowo. Zajętość (unikalność w bazie) to osobna sprawa,
    rozstrzygana dopiero przez create_link przy zapisie, nie tutaj.

    Wołane i z formularza (LinkForm.clean_custom_code — szybki feedback
    dla użytkownika), i z create_link (serwis nie ufa ślepo formularzowi,
    to samo API może kiedyś wołać coś innego niż ten formularz)."""
    if not CUSTOM_CODE_PATTERN.match(code):
        raise ValueError("Kod może zawierać tylko litery, cyfry, myślnik i podkreślnik")
    if not (CUSTOM_CODE_MIN_LENGTH <= len(code) <= CUSTOM_CODE_MAX_LENGTH):
        raise ValueError(f"Kod musi mieć od {CUSTOM_CODE_MIN_LENGTH} do {CUSTOM_CODE_MAX_LENGTH} znaków")
    if code.lower() in RESERVED_CODES:
        raise ValueError("Ten kod jest zastrzeżony")


def create_link(*, owner, target_url: str, code: str | None = None, password: str = "", **kwargs) -> Link:
    """Tworzy Link. Bez `code` losuje unikalny kod (patrz niżej), z `code`
    próbuje zapisać dokładnie ten jeden, podany przez użytkownika.

    Przy losowaniu nie sprawdzamy najpierw, czy kod jest wolny — dwa
    równoległe żądania mogłyby zobaczyć ten sam wolny kod. Zamiast tego
    próbujemy zapisać i reagujemy na IntegrityError z unikalnego indeksu,
    które jedyne potrafi to rozstrzygnąć atomowo. Przy własnym kodzie ten
    sam mechanizm daje darmową ochronę przed wyścigiem na tym samym
    wpisanym ręcznie kodzie — tylko bez pętli ponawiania (nie ma czego
    losować drugi raz), kolizja od razu wraca jako błąd do formularza.
    """
    password_hash = make_password(password) if password else ""

    if code is not None:
        validate_custom_code(code)
        try:
            with transaction.atomic():
                return Link.objects.create(
                    owner=owner,
                    target_url=target_url,
                    code=code,
                    password_hash=password_hash,
                    **kwargs,
                )
        except IntegrityError:
            raise ValueError("Ten kod jest już zajęty")

    for _ in range(MAX_GENERATE_ATTEMPTS):
        generated = generate_code()
        if generated.lower() in RESERVED_CODES:
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
                    code=generated,
                    password_hash=password_hash,
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
