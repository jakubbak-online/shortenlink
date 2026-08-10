from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from links.models import ClickEvent, Link


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
        link = Link.objects.create(
            code="cache5", target_url="https://example.com/cel", is_active=False
        )

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
        link = Link.objects.create(
            code="cache8", target_url="https://example.com/cel", max_clicks=3
        )
        url = reverse("links:redirect", args=[link.code])

        for _ in range(3):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class CreateLinkViewTests(TestCase):
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
