from django.test import TestCase
from django.urls import reverse

from links.models import ClickEvent, Link


class RedirectViewTests(TestCase):
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
