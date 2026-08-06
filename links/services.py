"""Logika biznesowa aplikacji links.

Widoki (i później serializery API) mają tylko wołać te funkcje, nie
duplikować logiki. Dzięki temu da się to przetestować bez klienta HTTP.
"""

import secrets

from django.db import IntegrityError, transaction

from links.models import Link

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
