from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from links.forms import LinkForm


def valid_data(**overrides):
    data = {"target_url": "https://example.com/dlugi-adres", "title": ""}
    data.update(overrides)
    return data


class LinkFormTests(TestCase):
    def test_minimalne_dane_sa_poprawne(self):
        form = LinkForm(data=valid_data())

        self.assertTrue(form.is_valid())

    def test_pusty_wlasny_kod_jest_dopuszczalny(self):
        form = LinkForm(data=valid_data(custom_code=""))

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["custom_code"], "")

    def test_niepoprawny_znak_we_wlasnym_kodzie_jest_bledem(self):
        form = LinkForm(data=valid_data(custom_code="ma spacje"))

        self.assertFalse(form.is_valid())
        self.assertIn("custom_code", form.errors)

    def test_zastrzezony_wlasny_kod_jest_bledem(self):
        form = LinkForm(data=valid_data(custom_code="admin"))

        self.assertFalse(form.is_valid())
        self.assertIn("custom_code", form.errors)

    def test_data_wygasniecia_w_przeszlosci_jest_bledem(self):
        wczoraj = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        form = LinkForm(data=valid_data(expires_at=wczoraj))

        self.assertFalse(form.is_valid())
        self.assertIn("expires_at", form.errors)

    def test_data_wygasniecia_w_przyszlosci_jest_poprawna(self):
        jutro = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        form = LinkForm(data=valid_data(expires_at=jutro))

        self.assertTrue(form.is_valid())

    def test_zerowy_limit_klikniec_jest_bledem(self):
        form = LinkForm(data=valid_data(max_clicks="0"))

        self.assertFalse(form.is_valid())
        self.assertIn("max_clicks", form.errors)

    def test_dodatni_limit_klikniec_jest_poprawny(self):
        form = LinkForm(data=valid_data(max_clicks="5"))

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["max_clicks"], 5)
