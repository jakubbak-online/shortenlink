from django.test import TestCase
from django.utils import timezone

from links.models import ClickEvent, Link
from links.services import classify_device, hash_ip, record_click

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


class HashIpTests(TestCase):
    def test_ten_sam_ip_daje_ten_sam_hash(self):
        self.assertEqual(hash_ip("1.2.3.4"), hash_ip("1.2.3.4"))

    def test_rozne_ip_daja_rozny_hash(self):
        self.assertNotEqual(hash_ip("1.2.3.4"), hash_ip("4.3.2.1"))

    def test_hash_nie_zawiera_surowego_ip(self):
        self.assertNotIn("1.2.3.4", hash_ip("1.2.3.4"))


class ClassifyDeviceTests(TestCase):
    def test_rozpoznaje_desktop(self):
        self.assertEqual(classify_device(DESKTOP_UA), "desktop")

    def test_rozpoznaje_mobile(self):
        self.assertEqual(classify_device(MOBILE_UA), "mobile")

    def test_bota_klasyfikuje_osobno_a_nie_jako_desktop(self):
        self.assertEqual(classify_device(BOT_UA), "bot")


class RecordClickTests(TestCase):
    def setUp(self):
        self.link = Link.objects.create(code="abc123", target_url="https://example.com")

    def test_zapisuje_zdarzenie_z_zahaszowanym_ip(self):
        record_click(
            link_id=self.link.id,
            ip="203.0.113.5",
            user_agent=DESKTOP_UA,
            referer="https://google.com/search?q=test",
            timestamp=timezone.now(),
        )

        event = ClickEvent.objects.get()
        self.assertEqual(event.link_id, self.link.id)
        self.assertEqual(event.device_type, "desktop")
        self.assertEqual(event.referer_domain, "google.com")
        self.assertEqual(event.ip_hash, hash_ip("203.0.113.5"))
        self.assertNotIn("203.0.113.5", event.ip_hash)

    def test_brak_referera_daje_pusty_referer_domain(self):
        record_click(
            link_id=self.link.id,
            ip="203.0.113.5",
            user_agent=DESKTOP_UA,
            referer="",
            timestamp=timezone.now(),
        )

        event = ClickEvent.objects.get()
        self.assertEqual(event.referer_domain, "")
