from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from links.models import ClickEvent, DailyStat, Link


class RedirectViewTests(TestCase):
    def setUp(self):
        # Cache Redis żyje poza transakcją testu (TestCase robi rollback
        # bazy, ale nie dotyka Redisa) - bez wyczyszczenia testy dzielące
        # ten sam kod widziałyby dane z poprzedniego testu.
        cache.clear()

    def test_przekierowuje_pod_docelowy_adres(self):
        link = Link.objects.create(code="abc123", target_url="https://example.com/cel")

        response = self.client.get(reverse("links:redirect", args=[link.code]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/cel")

    def test_nieistniejacy_kod_zwraca_404(self):
        response = self.client.get(reverse("links:redirect", args=["brakuje"]))

        self.assertEqual(response.status_code, 404)

    def test_klikniecie_zapisuje_zdarzenie(self):
        link = Link.objects.create(code="abc123", target_url="https://example.com/cel")

        self.client.get(
            reverse("links:redirect", args=[link.code]),
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            HTTP_REFERER="https://google.com/",
            REMOTE_ADDR="203.0.113.9",
        )

        event = ClickEvent.objects.get()
        self.assertEqual(event.link_id, link.id)
        self.assertEqual(event.referer_domain, "google.com")
        self.assertNotEqual(event.ip_hash, "203.0.113.9")


class RedirectViewCacheTests(TestCase):
    """Etap 3: cache Redis na ścieżce przekierowania + reguły
    is_active/expires_at/max_clicks liczone z danych w cache'u."""

    def setUp(self):
        cache.clear()

    def test_pierwsze_wejscie_zapisuje_dane_do_cache(self):
        link = Link.objects.create(code="cache1", target_url="https://example.com/cel")

        self.client.get(reverse("links:redirect", args=[link.code]))

        self.assertEqual(cache.get("link:cache1")["target_url"], "https://example.com/cel")

    def test_trafienie_w_cache_pomija_zapytanie_do_bazy(self):
        link = Link.objects.create(code="cache2", target_url="https://example.com/cel")
        url = reverse("links:redirect", args=[link.code])
        self.client.get(url)  # miss - zapełnia cache

        # Jedyne zapytanie do bazy przy trafieniu w cache to insert
        # ClickEvent w tasku Celery (odpalonym eager w testach) - Link
        # nie jest już odczytywany z Postgresa.
        with self.assertNumQueries(1):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/cel")

    def test_edycja_linku_uniewaznia_cache(self):
        link = Link.objects.create(code="cache3", target_url="https://example.com/stary")
        self.client.get(reverse("links:redirect", args=[link.code]))

        link.target_url = "https://example.com/nowy"
        link.save()

        response = self.client.get(reverse("links:redirect", args=[link.code]))
        self.assertEqual(response["Location"], "https://example.com/nowy")

    def test_usuniecie_linku_uniewaznia_cache(self):
        link = Link.objects.create(code="cache4", target_url="https://example.com/cel")
        self.client.get(reverse("links:redirect", args=[link.code]))

        link.delete()

        response = self.client.get(reverse("links:redirect", args=["cache4"]))
        self.assertEqual(response.status_code, 404)

    def test_nieaktywny_link_zwraca_404(self):
        link = Link.objects.create(code="cache5", target_url="https://example.com/cel", is_active=False)

        response = self.client.get(reverse("links:redirect", args=[link.code]))
        self.assertEqual(response.status_code, 404)

    def test_wygasly_link_zwraca_404(self):
        link = Link.objects.create(
            code="cache6",
            target_url="https://example.com/cel",
            expires_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(reverse("links:redirect", args=[link.code]))
        self.assertEqual(response.status_code, 404)

    def test_niewygasly_link_dziala(self):
        link = Link.objects.create(
            code="cache7",
            target_url="https://example.com/cel",
            expires_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(reverse("links:redirect", args=[link.code]))
        self.assertEqual(response.status_code, 302)

    def test_limit_klikniec_blokuje_po_przekroczeniu(self):
        link = Link.objects.create(code="cache8", target_url="https://example.com/cel", max_clicks=3)
        url = reverse("links:redirect", args=[link.code])

        for _ in range(3):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class RedirectViewPasswordTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_link_z_haslem_pokazuje_formularz_zamiast_przekierowania(self):
        Link.objects.create(
            code="haslo1",
            target_url="https://example.com/cel",
            password_hash=make_password("sezam"),
        )

        response = self.client.get(reverse("links:redirect", args=["haslo1"]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hasłem")

    def test_niepoprawne_haslo_nie_przekierowuje_i_nie_liczy_klikniecia(self):
        Link.objects.create(
            code="haslo2",
            target_url="https://example.com/cel",
            password_hash=make_password("sezam"),
        )

        response = self.client.post(reverse("links:redirect", args=["haslo2"]), {"password": "zle-haslo"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ClickEvent.objects.count(), 0)

    def test_poprawne_haslo_przekierowuje_i_liczy_klikniecie(self):
        Link.objects.create(
            code="haslo3",
            target_url="https://example.com/cel",
            password_hash=make_password("sezam"),
        )

        response = self.client.post(reverse("links:redirect", args=["haslo3"]), {"password": "sezam"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/cel")
        self.assertEqual(ClickEvent.objects.count(), 1)

    def test_link_bez_hasla_przekierowuje_od_razu(self):
        Link.objects.create(code="bezhasla", target_url="https://example.com/cel")

        response = self.client.get(reverse("links:redirect", args=["bezhasla"]))

        self.assertEqual(response.status_code, 302)


class CreateLinkViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_formularz_tworzy_link_i_pokazuje_krotki_adres(self):
        response = self.client.post(
            reverse("links:create"),
            {"target_url": "https://example.com/dlugi-adres", "title": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Link.objects.count(), 1)
        link = Link.objects.get()
        self.assertIsNone(link.owner)
        self.assertContains(response, f"/{link.code}/")

    def test_wlasny_kod_trafia_do_utworzonego_linku(self):
        response = self.client.post(
            reverse("links:create"),
            {"target_url": "https://example.com/dlugi-adres", "title": "", "custom_code": "moj-link"},
        )

        self.assertEqual(response.status_code, 200)
        link = Link.objects.get()
        self.assertEqual(link.code, "moj-link")
        self.assertContains(response, "/moj-link/")

    def test_zajety_wlasny_kod_pokazuje_blad_formularza_zamiast_500(self):
        Link.objects.create(code="zajety-kod", target_url="https://inny.example")

        response = self.client.post(
            reverse("links:create"),
            {"target_url": "https://example.com/dlugi-adres", "title": "", "custom_code": "zajety-kod"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "zajęty")
        self.assertEqual(Link.objects.count(), 1)


class StatsViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_pokazuje_liczbe_klikniec(self):
        link = Link.objects.create(code="abc123", target_url="https://example.com")
        self.client.get(reverse("links:redirect", args=[link.code]))
        self.client.get(reverse("links:redirect", args=[link.code]))

        response = self.client.get(reverse("links:stats", args=[link.code]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2")

    def test_nieistniejacy_kod_zwraca_404(self):
        response = self.client.get(reverse("links:stats", args=["brakuje"]))

        self.assertEqual(response.status_code, 404)

    def test_pokazuje_zagregowane_dane_z_dailystat(self):
        link = Link.objects.create(code="agr123", target_url="https://example.com")
        DailyStat.objects.create(link=link, date=date(2026, 8, 1), clicks=42, unique_visitors=10)

        response = self.client.get(reverse("links:stats", args=[link.code]))

        self.assertContains(response, "42")
        self.assertContains(response, "2026-08-01")


class RateLimitViewTests(TestCase):
    """Limity same w sobie (INCR + EXPIRE) są przetestowane w
    test_ratelimit.py - tutaj sprawdzamy tylko, że widoki faktycznie
    z nich korzystają i poprawnie zwracają 429 + Retry-After. Stałe
    limitów przycięte przez patch, żeby nie robić setek żądań w teście."""

    def setUp(self):
        cache.clear()

    @patch("links.views.RATE_LIMIT_CREATE_ANONYMOUS", 2)
    def test_anonim_po_przekroczeniu_limitu_dostaje_429(self):
        url = reverse("links:create")
        data = {"target_url": "https://example.com/x", "title": ""}

        for _ in range(2):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertEqual(Link.objects.count(), 2)

    @patch("links.views.RATE_LIMIT_CREATE_AUTHENTICATED", 2)
    def test_zalogowany_ma_osobny_wyzszy_limit(self):
        user = get_user_model().objects.create_user(username="uzytkownik", password="haslo123")
        self.client.force_login(user)
        url = reverse("links:create")
        data = {"target_url": "https://example.com/x", "title": ""}

        for _ in range(2):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 429)

    @patch("links.views.RATE_LIMIT_REDIRECT_PER_IP", 3)
    def test_przekierowanie_po_przekroczeniu_limitu_dostaje_429(self):
        link = Link.objects.create(code="limit1", target_url="https://example.com/cel")
        url = reverse("links:redirect", args=[link.code])

        for _ in range(3):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
