from django.core.cache import cache
from django.test import TestCase, override_settings
from freezegun import freeze_time

from links.ratelimit import RateLimitExceeded, check_rate_limit

# TTL na kluczach cache'u ustawia się realnie po stronie Redisa - to jego
# własny, prawdziwy zegar, którego freezegun (przestawiający zegar tylko
# w procesie Pythona) nie dotyka. Test resetu okna dlatego świadomie
# przełącza się na LocMemCache - wygasanie kluczy tam liczone jest przez
# time.time() w samym Pythonie, więc reaguje na freeze_time. Reszta
# testów w tym pliku zostaje na prawdziwym Redisie (domyślny CACHES),
# bo tam nie chodzi o wygasanie w czasie, tylko o samą logikę licznika.
LOCMEM_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class CheckRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_pierwsze_n_zadan_przechodzi(self):
        for _ in range(3):
            check_rate_limit("test-klucz", limit=3, window_seconds=60)  # nie rzuca

    def test_kolejne_zadanie_po_limicie_rzuca_wyjatek(self):
        for _ in range(3):
            check_rate_limit("test-klucz", limit=3, window_seconds=60)

        with self.assertRaises(RateLimitExceeded):
            check_rate_limit("test-klucz", limit=3, window_seconds=60)

    def test_retry_after_rowny_dlugosci_okna(self):
        check_rate_limit("test-klucz", limit=1, window_seconds=60)

        with self.assertRaises(RateLimitExceeded) as ctx:
            check_rate_limit("test-klucz", limit=1, window_seconds=60)

        self.assertEqual(ctx.exception.retry_after, 60)

    def test_rozne_klucze_maja_niezalezne_liczniki(self):
        check_rate_limit("klucz-a", limit=1, window_seconds=60)
        check_rate_limit("klucz-b", limit=1, window_seconds=60)  # nie rzuca - inny klucz

    @override_settings(CACHES=LOCMEM_CACHES)
    def test_po_uplywie_okna_licznik_sie_resetuje(self):
        with freeze_time("2026-01-01 12:00:00") as frozen:
            check_rate_limit("test-klucz", limit=1, window_seconds=60)
            with self.assertRaises(RateLimitExceeded):
                check_rate_limit("test-klucz", limit=1, window_seconds=60)

            frozen.tick(delta=61)  # przeskok w czasie zamiast time.sleep()

            check_rate_limit("test-klucz", limit=1, window_seconds=60)  # nowe okno, nie rzuca
