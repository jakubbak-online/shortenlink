from unittest.mock import patch

from django.contrib.auth.hashers import check_password
from django.test import TestCase

from links.models import Link
from links.services import ALPHABET, CODE_LENGTH, create_link, generate_code, validate_custom_code


class GenerateCodeTests(TestCase):
    def test_zwraca_kod_o_ustalonej_dlugosci_z_alfabetu(self):
        code = generate_code()

        self.assertEqual(len(code), CODE_LENGTH)
        self.assertTrue(all(char in ALPHABET for char in code))


class CreateLinkTests(TestCase):
    def test_ponawia_przy_kolizji_kodu(self):
        Link.objects.create(target_url="https://istniejacy.example", code="AAAAAA")

        with patch(
            "links.services.generate_code",
            side_effect=["AAAAAA", "AAAAAA", "BBBBBB"],
        ):
            link = create_link(owner=None, target_url="https://nowy.example")

        self.assertEqual(link.code, "BBBBBB")
        self.assertEqual(Link.objects.count(), 2)

    def test_pomija_zastrzezone_slowo(self):
        with patch("links.services.generate_code", side_effect=["admin", "CCCCCC"]):
            link = create_link(owner=None, target_url="https://nowy.example")

        self.assertEqual(link.code, "CCCCCC")

    def test_poddaje_sie_po_wyczerpaniu_prob(self):
        with patch("links.services.generate_code", return_value="admin"):
            with self.assertRaises(RuntimeError):
                create_link(owner=None, target_url="https://nowy.example")

    def test_wlasny_kod_tworzy_link_z_tym_kodem(self):
        link = create_link(owner=None, target_url="https://nowy.example", code="moja-promocja")

        self.assertEqual(link.code, "moja-promocja")

    def test_wlasny_kod_zajety_podnosi_blad(self):
        Link.objects.create(target_url="https://istniejacy.example", code="zajety")

        with self.assertRaises(ValueError):
            create_link(owner=None, target_url="https://nowy.example", code="zajety")

    def test_wlasny_kod_zastrzezony_podnosi_blad(self):
        with self.assertRaises(ValueError):
            create_link(owner=None, target_url="https://nowy.example", code="admin")

    def test_haslo_jest_haszowane(self):
        link = create_link(owner=None, target_url="https://nowy.example", password="tajne-haslo")

        self.assertNotEqual(link.password_hash, "tajne-haslo")
        self.assertTrue(check_password("tajne-haslo", link.password_hash))

    def test_bez_hasla_password_hash_jest_pusty(self):
        link = create_link(owner=None, target_url="https://nowy.example")

        self.assertEqual(link.password_hash, "")


class ValidateCustomCodeTests(TestCase):
    def test_akceptuje_litery_cyfry_myslnik_podkreslnik(self):
        validate_custom_code("moj-kod_123")  # nie rzuca

    def test_odrzuca_niedozwolone_znaki(self):
        with self.assertRaises(ValueError):
            validate_custom_code("kod ze spacja")

    def test_odrzuca_za_krotki(self):
        with self.assertRaises(ValueError):
            validate_custom_code("ab")

    def test_odrzuca_za_dlugi(self):
        with self.assertRaises(ValueError):
            validate_custom_code("a" * 17)

    def test_odrzuca_zastrzezone_slowo_niezaleznie_od_wielkosci_liter(self):
        with self.assertRaises(ValueError):
            validate_custom_code("Admin")
