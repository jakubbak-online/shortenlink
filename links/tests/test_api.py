from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from links.models import Link


class LinkApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.alice = User.objects.create_user(username="alice", password="haslo123")
        self.bob = User.objects.create_user(username="bob", password="haslo123")
        self.alice_client = APIClient()
        self.alice_client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.alice).key}")
        self.bob_client = APIClient()
        self.bob_client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.bob).key}")


class AuthTests(LinkApiTestCase):
    def test_bez_tokenu_dostaje_401(self):
        response = APIClient().get("/api/links/")

        self.assertEqual(response.status_code, 401)

    def test_token_endpoint_zwraca_token_dla_poprawnych_danych(self):
        response = self.client.post(
            reverse("api-token"), {"username": "alice", "password": "haslo123"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.json())

    def test_token_endpoint_odrzuca_zle_haslo(self):
        response = self.client.post(
            reverse("api-token"), {"username": "alice", "password": "zle-haslo"}
        )

        self.assertEqual(response.status_code, 400)


class LinkCrudTests(LinkApiTestCase):
    def test_tworzy_link_przypisany_do_zalogowanego_uzytkownika(self):
        response = self.alice_client.post("/api/links/", {"target_url": "https://example.com/x"})

        self.assertEqual(response.status_code, 201)
        link = Link.objects.get()
        self.assertEqual(link.owner, self.alice)
        self.assertIn("short_url", response.json())

    def test_wlasny_kod_i_haslo_przez_api(self):
        response = self.alice_client.post(
            "/api/links/",
            {"target_url": "https://example.com/x", "custom_code": "przez-api", "password": "tajne"},
        )

        self.assertEqual(response.status_code, 201)
        link = Link.objects.get()
        self.assertEqual(link.code, "przez-api")
        self.assertTrue(check_password("tajne", link.password_hash))
        # write_only - hasło (ani jego hash) nigdy nie wraca w odpowiedzi
        self.assertNotIn("password", response.json())

    def test_zajety_wlasny_kod_zwraca_400_nie_500(self):
        Link.objects.create(code="zajety", target_url="https://inny.example")

        response = self.alice_client.post(
            "/api/links/", {"target_url": "https://example.com/x", "custom_code": "zajety"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Link.objects.count(), 1)

    def test_widzi_i_edytuje_wlasny_link(self):
        link = Link.objects.create(owner=self.alice, code="mojlink", target_url="https://stary.example")

        get_response = self.alice_client.get("/api/links/mojlink/")
        self.assertEqual(get_response.status_code, 200)

        patch_response = self.alice_client.patch(
            "/api/links/mojlink/", {"target_url": "https://nowy.example"}
        )
        self.assertEqual(patch_response.status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.target_url, "https://nowy.example")

    def test_cudzy_link_zwraca_404_nie_403(self):
        Link.objects.create(owner=self.alice, code="alicelink", target_url="https://example.com")

        get_response = self.bob_client.get("/api/links/alicelink/")
        patch_response = self.bob_client.patch("/api/links/alicelink/", {"title": "przejety"})
        delete_response = self.bob_client.delete("/api/links/alicelink/")

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)

    def test_link_bez_wlasciciela_niewidoczny_przez_api(self):
        # Linki tworzone anonimowo przez formularz webowy (owner=None)
        # nie należą do nikogo w API - świadomie niewidoczne dla nikogo,
        # nie tylko dla "obcych".
        Link.objects.create(code="anonimowy", target_url="https://example.com")

        response = self.alice_client.get("/api/links/anonimowy/")

        self.assertEqual(response.status_code, 404)

    def test_lista_zwraca_tylko_wlasne_linki(self):
        Link.objects.create(owner=self.alice, code="alicelink", target_url="https://a.example")
        Link.objects.create(owner=self.bob, code="boblink", target_url="https://b.example")

        response = self.alice_client.get("/api/links/")

        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["alicelink"])

    def test_usuwa_wlasny_link(self):
        Link.objects.create(owner=self.alice, code="dokasacji", target_url="https://example.com")

        response = self.alice_client.delete("/api/links/dokasacji/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Link.objects.filter(code="dokasacji").exists())


class PaginationTests(LinkApiTestCase):
    def test_paginacja_ogranicza_wyniki_do_page_size(self):
        for i in range(25):
            Link.objects.create(owner=self.alice, code=f"link{i:03d}", target_url=f"https://example.com/{i}")

        response = self.alice_client.get("/api/links/")
        body = response.json()

        self.assertEqual(body["count"], 25)
        self.assertEqual(len(body["results"]), 20)  # PAGE_SIZE z settings.py
        self.assertIsNotNone(body["next"])


class StatsActionTests(LinkApiTestCase):
    def test_zwraca_liczbe_klikniec_i_zdarzenia(self):
        link = Link.objects.create(owner=self.alice, code="statslink", target_url="https://example.com")
        self.client.get(reverse("links:redirect", args=[link.code]))
        self.client.get(reverse("links:redirect", args=[link.code]))

        response = self.alice_client.get("/api/links/statslink/stats/")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["total_clicks"], 2)
        self.assertEqual(len(body["recent_events"]), 2)

    def test_cudzy_link_stats_zwraca_404(self):
        Link.objects.create(owner=self.alice, code="statslink2", target_url="https://example.com")

        response = self.bob_client.get("/api/links/statslink2/stats/")

        self.assertEqual(response.status_code, 404)
