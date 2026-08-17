# shortenlink

Skracacz linków z analityką kliknięć. Jedno zdanie, o które tu chodzi:
**przekierowanie musi być natychmiastowe, a zapis analityki jest wolny —
więc te dwie rzeczy są rozdzielone**: przekierowanie czyta z cache'u i
odpowiada od razu, zapis kliknięcia (parsowanie User-Agenta, lookup
kraju, insert do bazy) leci do kolejki i dzieje się w tle, już po tym,
jak użytkownik dostał odpowiedź.

## Uruchomienie

```bash
cp .env.example .env      # i uzupełnij SECRET_KEY / IP_SALT
docker compose up
```

To wszystko. Migracje i `collectstatic` nakładają się same przy starcie
(`entrypoint.sh`). Aplikacja stoi pod `http://localhost:8000/`.

## Jak to działa (ścieżka przekierowania)

```
                    GET /<code>/
przeglądarka  ─────────────────────▶  Django (gunicorn)
                                            │
                              cache hit     │     cache miss
                       (Redis: link:<code>)│  (Postgres, potem zapis do cache'u)
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                          dane linku              SELECT z Postgresa
                              │                           │
                              └─────────────┬─────────────┘
                                            ▼
                     is_active? / expires_at? / hasło? / max_clicks?
                              (limit liczony INCR-em w Redisie,
                               nie COUNT(*) na zdarzeniach)
                                            │
                                            ▼
                              302 → target_url  ◀── przeglądarka dostaje to OD RAZU
                                            │
                                            ┆  (w tle, po wysłaniu odpowiedzi)
                                            ▼
                                  Celery worker: parsuje User-Agenta,
                                  hashuje IP, dolicza kraj, zapisuje
                                  ClickEvent w Postgresie
                                            │
                          co noc, Celery beat ▼
                          agreguje wczorajsze ClickEvent → DailyStat
                          (dashboard czyta stąd, nie ze zdarzeń)
                          i czyści zdarzenia starsze niż 90 dni
```

## Decyzje projektowe

**Zapis kliknięcia jest asynchroniczny.** Insert do Postgresa, parsowanie
User-Agenta i lookup geolokalizacyjny to kilkanaście milisekund
doklejone do *każdego* przekierowania — a nikt nie patrzy na dashboard w
tej samej sekundzie, w której ktoś kliknął. Widok wrzuca zadanie do
Celery i natychmiast zwraca `302`; cała wolna robota dzieje się w
workerze, po odpowiedzi. Koszt: jeśli worker akurat nie działa,
przekierowania idą dalej bez przeszkód, ale pojedyncze kliknięcia z tego
okresu się nie zapiszą — świadomie zaakceptowane, to analityka, nie
rozliczenia finansowe.

**`302`, nie `301`.** Przekierowanie trwałe przeglądarka zapamiętuje na
stałe i przy kolejnych wejściach w ogóle nie odpytuje serwera —
analityka przestaje działać, a zmiana docelowego adresu nigdy nie
dotrze do osób, które już raz kliknęły. `302` wymusza zapytanie za
każdym razem, kosztem tego, że każde kliknięcie to realny request
zamiast lokalnej pamięci przeglądarki.

**Kolizje kodów obsługiwane przez `IntegrityError`, nie `exists()`.**
Sprawdzenie "czy kod jest wolny", a potem zapis to klasyczny wyścig —
dwa równoległe żądania mogą zobaczyć ten sam wolny kod i oba spróbować
go zapisać. Jedyna instancja, która potrafi to rozstrzygnąć atomowo, to
unikalny indeks w bazie: kod próbuje zapisać, łapie wyjątek przy
kolizji, ponawia (maks. 5 razy, w praktyce prawie nigdy nie potrzeba
więcej niż jednej próby na przestrzeni 62⁶ możliwych kodów).

**`DailyStat` jako celowa denormalizacja.** Wykres za 30-90 dni liczony
z surowych `ClickEvent` przy każdym wejściu na dashboard oznacza
skanowanie i grupowanie coraz większej liczby wierszy. Nocne zadanie
Celery Beat liczy to raz dziennie i zapisuje garść zagregowanych
wierszy zamiast tego. Dodatkowa korzyść: te wiersze przeżywają retencję
surowych zdarzeń (90 dni), więc historyczne liczby zostają, nawet gdy
źródłowe zdarzenia już dawno zniknęły.

**Hash IP zamiast surowego adresu.** RODO traktuje adres IP jako dane
osobowe. Do liczenia unikalnych wejść w danym dniu hash z solą (sól w
zmiennej środowiskowej, nie w repo) wystarcza w zupełności, a nie
przechowuje niczego, co identyfikuje osobę.

Do tego jedno świadome odejście od typowego schematu: `Link.owner` jest
**nullable** — anonimowe tworzenie linków jest zamierzoną funkcją (ma
własny, niższy limit ruchu), nie przeoczeniem.

## Wyniki pomiarów

Metodologia: [Locust](https://locust.io) (`benchmarks/locustfile.py`),
scenariusz "50 użytkowników bije w ten sam krótki link przez minutę",
mediana i 95. percentyl czasu odpowiedzi.

Wersja z etapu 2 (zapis kliknięcia **synchronicznie**, w widoku, bez
cache'u) była mierzona lokalnie na SQLite, zanim środowisko dockerowe
było gotowe — z tego pomiaru wynika jasny sygnał: mediana wygląda
niewinnie (150 ms), ale 95. percentyl sięga kilkunastu **sekund**, bo
ogon rozkładu degraduje się pod obciążeniem dużo wcześniej, niż widać to
w samej średniej. Formalny, jednakowy pomiar "przed/po" na docelowym
stosie (Postgres + Redis + Celery w Dockerze, nie SQLite) jest w
przygotowaniu — SQLite ma inny model blokad przy współbieżnych zapisach
niż Postgres, więc nie jest wiarygodnym punktem odniesienia dla
ostatecznych liczb.

## Testy

```bash
pip install -r requirements-dev.txt
pytest
```

W kontenerze: `docker compose exec web pytest`. Konfiguracja testowa
odpala zadania Celery synchronicznie (`CELERY_TASK_ALWAYS_EAGER`) i
używa szybkiego hashera haseł zamiast produkcyjnego PBKDF2 — sam test
nie musi być tak samo drogi obliczeniowo jak prawdziwe logowanie.

Lint: `ruff check .` i `ruff format --check .` (uruchamiane też w CI
przy każdym pushu, razem z pytest, na usługowych kontenerach Postgresa
i Redisa).
