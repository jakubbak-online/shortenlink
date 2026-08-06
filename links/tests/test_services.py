from unittest.mock import patch

from django.test import TestCase

from links.models import Link
from links.services import ALPHABET, CODE_LENGTH, create_link, generate_code


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
