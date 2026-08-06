from django.test import TestCase
from django.urls import reverse

from links.models import Link


class RedirectViewTests(TestCase):
    def test_przekierowuje_pod_docelowy_adres(self):
        link = Link.objects.create(code="abc123", target_url="https://example.com/cel")

        response = self.client.get(reverse("links:redirect", args=[link.code]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://example.com/cel")

    def test_nieistniejacy_kod_zwraca_404(self):
        response = self.client.get(reverse("links:redirect", args=["brakuje"]))

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
