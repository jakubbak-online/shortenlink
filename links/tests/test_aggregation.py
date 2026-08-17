from datetime import date, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from links.models import ClickEvent, DailyStat, Link
from links.services import (
    aggregate_daily_stats_for_date,
    link_total_clicks,
    purge_old_click_events,
)


def _at(date_str: str, time_str: str = "12:00:00"):
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    return timezone.make_aware(naive)


class AggregateDailyStatsTests(TestCase):
    def setUp(self):
        self.link = Link.objects.create(code="abc123", target_url="https://example.com")

    def _create_events(self, count, date_str, device_type="desktop", ip_prefix="a"):
        # i % 50 -> zawsze 50 unikalnych ip_hash niezależnie od count, żeby
        # test na unique_visitors miał przewidywalną liczbę do sprawdzenia.
        events = [
            ClickEvent(
                link=self.link,
                created_at=_at(date_str, f"{i % 24:02d}:00:00"),
                ip_hash=f"{ip_prefix}-{i % 50}",
                device_type=device_type,
            )
            for i in range(count)
        ]
        ClickEvent.objects.bulk_create(events)

    def test_agreguje_trzysta_zdarzen_ze_spreparowana_data(self):
        self._create_events(300, "2026-08-10")

        touched = aggregate_daily_stats_for_date(date(2026, 8, 10))

        stat = DailyStat.objects.get(link=self.link, date=date(2026, 8, 10))
        self.assertEqual(touched, 1)
        self.assertEqual(stat.clicks, 300)
        self.assertEqual(stat.unique_visitors, 50)

    def test_wyklucza_boty_z_agregacji(self):
        self._create_events(10, "2026-08-10", device_type="desktop", ip_prefix="a")
        self._create_events(5, "2026-08-10", device_type="bot", ip_prefix="b")

        aggregate_daily_stats_for_date(date(2026, 8, 10))

        stat = DailyStat.objects.get(link=self.link, date=date(2026, 8, 10))
        self.assertEqual(stat.clicks, 10)

    def test_granica_dnia_nie_wpada_do_zlego_dnia(self):
        # Klasyczna pomyłka o jeden dzień: 23:59:59 i 00:00:00 następnego
        # dnia różnią się o sekundę, ale mają trafić do różnych DailyStat.
        ClickEvent.objects.create(
            link=self.link,
            created_at=_at("2026-08-10", "23:59:59"),
            ip_hash="a",
            device_type="desktop",
        )
        ClickEvent.objects.create(
            link=self.link,
            created_at=_at("2026-08-11", "00:00:00"),
            ip_hash="b",
            device_type="desktop",
        )

        aggregate_daily_stats_for_date(date(2026, 8, 10))
        aggregate_daily_stats_for_date(date(2026, 8, 11))

        self.assertEqual(DailyStat.objects.get(link=self.link, date=date(2026, 8, 10)).clicks, 1)
        self.assertEqual(DailyStat.objects.get(link=self.link, date=date(2026, 8, 11)).clicks, 1)

    def test_ponowne_uruchomienie_nadpisuje_a_nie_dubluje(self):
        self._create_events(10, "2026-08-10", ip_prefix="a")
        aggregate_daily_stats_for_date(date(2026, 8, 10))

        self._create_events(5, "2026-08-10", ip_prefix="b")
        aggregate_daily_stats_for_date(date(2026, 8, 10))

        rows = DailyStat.objects.filter(link=self.link, date=date(2026, 8, 10))
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().clicks, 15)


class PurgeOldClickEventsTests(TestCase):
    def setUp(self):
        self.link = Link.objects.create(code="abc123", target_url="https://example.com")

    def test_kasuje_tylko_starsze_niz_retencja(self):
        old = ClickEvent.objects.create(
            link=self.link,
            created_at=timezone.now() - timedelta(days=91),
            ip_hash="a",
            device_type="desktop",
        )
        recent = ClickEvent.objects.create(
            link=self.link,
            created_at=timezone.now() - timedelta(days=10),
            ip_hash="b",
            device_type="desktop",
        )

        deleted = purge_old_click_events(retention_days=90)

        self.assertEqual(deleted, 1)
        self.assertFalse(ClickEvent.objects.filter(pk=old.pk).exists())
        self.assertTrue(ClickEvent.objects.filter(pk=recent.pk).exists())


class LinkTotalClicksTests(TestCase):
    def setUp(self):
        self.link = Link.objects.create(code="abc123", target_url="https://example.com")

    def test_liczy_historyczne_i_dzisiejsze_razem(self):
        DailyStat.objects.create(link=self.link, date=date(2026, 8, 1), clicks=7, unique_visitors=3)
        ClickEvent.objects.create(
            link=self.link,
            created_at=timezone.now(),
            ip_hash="x",
            device_type="desktop",
        )

        self.assertEqual(link_total_clicks(self.link), 8)

    def test_przezywa_purge_starych_zdarzen(self):
        old_date = timezone.now().date() - timedelta(days=95)
        for i in range(3):
            ClickEvent.objects.create(
                link=self.link,
                created_at=_at(old_date.isoformat(), f"{i:02d}:00:00"),
                ip_hash=f"h{i}",
                device_type="desktop",
            )
        aggregate_daily_stats_for_date(old_date)

        purge_old_click_events(retention_days=90)

        # Surowe zdarzenia znikają, ale suma zostaje - już jest w DailyStat.
        self.assertEqual(ClickEvent.objects.filter(link=self.link).count(), 0)
        self.assertEqual(link_total_clicks(self.link), 3)
