"""Rate limiting na Redisie, własna implementacja - nie gotowa
biblioteka, bo to piętnaście linijek i chodzi o zrozumienie mechanizmu,
nie o oszczędność kodu.

Wzorzec z sekcji 4.4 specyfikacji: INCR + EXPIRE, EXPIRE ustawiane tylko
przy pierwszym trafieniu w oknie. To jest okno "sztywne" (fixed window)
liczone od pierwszego żądania, nie "przesuwające się" (sliding window) -
prostsze, ale w teorii dopuszcza do 2x limitu ruchu w okolicach granicy
okna (np. limit 10/min: 10 żądań tuż przed końcem okna + 10 tuż po jego
odnowieniu). Sliding window wymagałby posortowanych zbiorów w Redisie
albo token bucketa - świadomie poza zakresem tego projektu.

Django's RedisCache.incr() nie tworzy licznika na nieistniejącym kluczu
(rzuca ValueError - sprawdzone eksperymentalnie w manage.py shell, w
przeciwieństwie do gołego Redisowego INCR, które by go stworzyło), więc
"EXPIRE tylko przy pierwszym trafieniu" implementujemy przez
cache.add() - atomowe "ustaw, jeśli klucza jeszcze nie ma", z TTL
przekazanym tylko w tym pierwszym wywołaniu."""

from django.core.cache import cache


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Limit żądań przekroczony, spróbuj ponownie za {retry_after}s")


def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    """Rzuca RateLimitExceeded po przekroczeniu limitu w oknie
    window_seconds. Nic nie zwraca przy sukcesie - liczy się brak
    wyjątku, tak jak przy pozostałych walidacjach w tym projekcie."""
    cache.add(key, 0, timeout=window_seconds)
    count = cache.incr(key)
    if count > limit:
        # Retry-After to długość całego okna, nie realny czas do jego
        # końca (Django cache nie eksponuje TTL istniejącego klucza) -
        # bezpieczna górna granica, klient poczeka najwyżej tyle, ile
        # trzeba, nigdy mniej niż trzeba.
        raise RateLimitExceeded(retry_after=window_seconds)
