"""Scenariusz obciazeniowy: wielu uzytkownikow bije w jeden krotki link.

Uzycie (host bez koncowego slasha):
    locust -f benchmarks/locustfile.py --host=http://localhost:8000

Potem w UI (http://localhost:8089) ustawic 50 uzytkownikow, spawn rate
np. 10/s, czas 1 minuta. Interesuja nas RPS, mediana i 95. percentyl
czasu odpowiedzi z zakladki "Statistics".

Ten sam scenariusz sluzy do pomiaru "przed" (zapis synchroniczny w
widoku) i "po" (cache + Celery) - tylko tak porownanie ma sens.
"""

import re

import requests
from locust import HttpUser, constant, events, task

TARGET_CODE = None


@events.test_start.add_listener
def create_target_link(environment, **kwargs):
    """Tworzy jeden link przed startem roju i zapamietuje jego kod -
    wszyscy uzytkownicy biją w ten sam, popularny link."""
    global TARGET_CODE

    host = environment.host
    session = requests.Session()

    index_page = session.get(f"{host}/")
    token = re.search(r'csrfmiddlewaretoken" value="([^"]+)"', index_page.text).group(1)

    response = session.post(
        f"{host}/",
        data={
            "csrfmiddlewaretoken": token,
            "target_url": "https://example.com/locust-benchmark",
            "title": "benchmark",
        },
        headers={"Referer": f"{host}/"},
    )
    match = re.search(rf"{re.escape(host)}/([0-9a-zA-Z]{{6}})/", response.text)
    if not match:
        raise RuntimeError("Nie udalo sie utworzyc linku testowego - sprawdz, czy serwer stoi")

    TARGET_CODE = match.group(1)
    print(f"Link testowy: {TARGET_CODE}")


class RedirectUser(HttpUser):
    wait_time = constant(0)

    @task
    def click_short_link(self):
        self.client.get(f"/{TARGET_CODE}/", name="/<code>/", allow_redirects=False)
