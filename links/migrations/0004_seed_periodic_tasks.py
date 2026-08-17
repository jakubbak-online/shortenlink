"""Zasiewa harmonogram Beat (agregacja + retencja) tak, żeby działał od
razu po `docker compose up`, bez ręcznego klikania w panelu admina.
Trzymane jako migracja danych - nie w CELERY_BEAT_SCHEDULE w settings.py -
bo DatabaseScheduler i tak czyta harmonogram z bazy, a nie z pliku."""

from django.db import migrations


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    aggregate_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name="Agregacja dziennych statystyk",
        defaults={"task": "links.tasks.aggregate_daily_stats", "crontab": aggregate_schedule},
    )

    # 15 minut po agregacji, nie w tej samej minucie - żeby nie liczyć się
    # z zadaniem powyżej o zasoby, gdyby oba akurat trwały dłużej niż zwykle.
    purge_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name="Retencja starych zdarzen",
        defaults={"task": "links.tasks.purge_old_events", "crontab": purge_schedule},
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        task__in=["links.tasks.aggregate_daily_stats", "links.tasks.purge_old_events"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("links", "0003_dailystat"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
