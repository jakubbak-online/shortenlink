# skroclinka.pl

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5-37814A?logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![DRF](https://img.shields.io/badge/Django%20REST-Framework-A30000?logo=django&logoColor=white)
![pytest](https://img.shields.io/badge/tested%20with-pytest-0A9EDC?logo=pytest&logoColor=white)
[![CI](https://github.com/jakubbak-online/skroclinka.pl/actions/workflows/ci.yml/badge.svg)](https://github.com/jakubbak-online/skroclinka.pl/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

*English version: [README.md](README.md)*

**Na żywo**: [skroclinka.pl](https://skroclinka.pl)

Skracacz linków z analityką kliknięć. Jedno zdanie, o co tu chodzi:
**przekierowanie musi być natychmiastowe, a zapis analityki jest wolny,
więc te dwie rzeczy są rozdzielone.** Przekierowanie czyta z cache'u i
odpowiada od razu; zapis kliknięcia (parsowanie User-Agenta, hash IP,
lookup kraju, insert do bazy) leci do kolejki i dzieje się w tle, już po
tym, jak użytkownik dostał odpowiedź.

Zrobione solo jako projekt do portfolio, żeby przećwiczyć jeden konkretny
problem od początku do końca (rozdzielenie szybkiej ścieżki od wolnego
zapisu), a nie żeby odhaczyć listę funkcji Django. Każda decyzja
projektowa niżej odpowiada na "dlaczego", nie tylko "co", łącznie z
tymi, które za pierwszym razem były błędne i złapał je test albo
prawdziwy deploy.

## Spis treści

- [Najważniejsze cechy](#najważniejsze-cechy)
- [Architektura](#architektura)
- [Stos technologiczny](#stos-technologiczny)
- [Struktura projektu](#struktura-projektu)
- [Konfiguracja lokalna](#konfiguracja-lokalna)
- [Uruchomienie](#uruchomienie)
- [Przegląd funkcji](#przegląd-funkcji)
- [Testy](#testy)
- [API](#api)
- [Szczegóły komponentów](#szczegóły-komponentów)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)
- [Bezpieczeństwo](#bezpieczeństwo)
- [Plany na przyszłość](#plany-na-przyszłość)
- [Autor i licencja](#autor-i-licencja)

## Najważniejsze cechy

- **Natychmiastowe przekierowania pod obciążeniem, zmierzone, nie
  zadeklarowane.** Synchroniczna wersja widoku przekierowania (sprzed
  cache'u) była mierzona Locustem, zanim została zastąpiona; wersja
  asynchroniczna z cache'em jest mierzona tym samym scenariuszem
  potem: "szybciej" to liczba, nie twierdzenie. Patrz [Testy](#testy).
- **Wyścigi rozwiązane na poziomie bazy danych, nie w logice
  aplikacji.** Kolizje kodów obsługiwane są przez złapanie
  `IntegrityError` z unikalnego indeksu i ponowienie, każda próba we
  własnym savepoincie `transaction.atomic()`, nie przez sprawdzenie
  `exists()` najpierw (klasyczny wyścig przy równoległych żądaniach).
- **Zdenormalizowana tabela agregatów, nie większy cache.** `DailyStat`
  liczony jest raz w nocy przez Celery Beat z surowych `ClickEvent` i
  przeżywa je: zadanie retencji (90 dni) może skasować miliony wierszy
  bez utraty ani jednego dnia historycznych danych na wykresie.
- **RODO uwzględnione w projekcie, nie doklejone później.** Adresy IP
  nigdy nie są zapisywane wprost, tylko hash SHA-256 z solą, co
  wystarcza do liczenia unikalnych wejść w danym dniu, nie identyfikuje
  nikogo. Surowe zdarzenia kasowane po 90 dniach; agregaty, które je
  przeżywają, nie zawierają żadnych danych osobowych.
- **Prawdziwy deploy, nie zrzut ekranu z `runserver`.** Pięć usług w
  Dockerze (Postgres, Redis, Django/gunicorn, worker Celery, Celery
  Beat) plus Caddy jako reverse proxy, na droplecie DigitalOcean, z
  automatycznym HTTPS z Let's Encrypt i CD z GitHub Actions przy każdym
  pushu na `main`.
- **`404`, nie `403`, dla cudzych linków.** Queryset API filtrowany jest
  do właściciela żądania przed jakimkolwiek zapytaniem, więc cudzy link
  po prostu nie istnieje z punktu widzenia endpointu, zero wycieku
  informacji o tym, czy dany kod jest zajęty.
- **Każdy błąd niżej jest prawdziwy**, nie hipotetyczny. Sekcja
  [Rozwiązywanie problemów](#rozwiązywanie-problemów) to dziennik
  rzeczy, które faktycznie się wysypały podczas budowy, i jak każda z
  nich została znaleziona.

## Architektura

```
                    GET /<code>/
przeglądarka  ─────────────────────▶  Caddy (HTTPS, Let's Encrypt)  ──▶  Django (gunicorn)
                                                                              │
                                                            cache hit         │        cache miss
                                                      (Redis: link:<code>)   │   (Postgres, potem zapis do cache'u)
                                                            ┌─────────────────┴─────────────────┐
                                                            ▼                                     ▼
                                                        dane linku                         SELECT z Postgresa
                                                            │                                     │
                                                            └─────────────────┬───────────────────┘
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
                                                                  hashuje IP, dolicza kraj,
                                                                  zapisuje ClickEvent w Postgresie
                                                                              │
                                                          co noc, Celery beat ▼
                                                          agreguje wczorajsze ClickEvent → DailyStat
                                                          (dashboard czyta stąd, nie ze zdarzeń)
                                                          i czyści zdarzenia starsze niż 90 dni
```

Pełny, krok po kroku opis każdego elementu tego diagramu jest w
[Szczegółach komponentów](#szczegóły-komponentów).

## Stos technologiczny

| Technologia | Do czego |
|---|---|
| **Django 6.0 / Python 3.13** | Sama aplikacja, podzielona na cienką warstwę widoków i warstwę logiki biznesowej (`services.py`), z której korzystają zarówno widoki, jak i REST API |
| **PostgreSQL 16** | Trwałe przechowywanie linków, zdarzeń kliknięć i dziennych agregatów |
| **Redis 7** | Trzy role na dwóch bazach logicznych: cache przekierowań + liczniki rate limitu (baza 0), broker Celery (baza 1); osobno, żeby ręczny `FLUSHDB` na jednej nie ruszał drugiej |
| **Celery + Celery Beat** | Asynchroniczny zapis kliknięć plus dwa nocne zadania (agregacja, retencja), harmonogram w tabeli bazy danych przez `django-celery-beat`, więc edytowalny z panelu admina bez redeployu |
| **Django REST Framework + drf-spectacular** | CRUD API na linkach z autoryzacją tokenem, automatycznie generowany schemat OpenAPI pod `/api/docs/` |
| **Docker Compose** | Dwie topologie: dev (bind mounty, porty wystawione bezpośrednio) i produkcyjna (bez bind mountów, bez wystawionych portów bazy/Redisa, Caddy jako jedyne wejście) |
| **Caddy 2** | Reverse proxy z w pełni automatycznym HTTPS (Let's Encrypt, razem z odnawianiem), sterowany jedną zmienną środowiskową `DOMAIN` |
| **gunicorn + WhiteNoise** | Produkcyjny serwer WSGI i skompresowane, wersjonowane serwowanie plików statycznych, bez osobnego nginx/CDN |
| **pytest + pytest-django** | 80 testów, przeniesionych w trakcie projektu z `manage.py test` (patrz [Rozwiązywanie problemów](#rozwiązywanie-problemów)) |
| **ruff** | Linting i formatowanie, egzekwowane w CI |
| **GitHub Actions** | CI (ruff + pytest na prawdziwych kontenerach Postgresa/Redisa) i CD (deploy przez SSH, warunkowany zielonym CI i tylko na pushach do `main`) |
| **Locust** | Testy obciążeniowe ścieżki przekierowania, żeby mieć prawdziwe liczby przed/po, nie szacunki |

## Struktura projektu

```
skroclinka.pl/
├── config/                   ustawienia Django, główny URLconf, aplikacja Celery
├── links/
│   ├── models.py              Link, ClickEvent, DailyStat
│   ├── services.py            logika biznesowa: generowanie kodów, obsługa kolizji,
│   │                          hash IP, klasyfikacja urządzeń, agregacja, retencja
│   ├── views.py                ścieżka przekierowania (ta krytyczna) + formularz tworzenia
│   ├── tasks.py                cienkie wrappery Celery nad services.py
│   ├── ratelimit.py            własny rate limiter na Redisie (okno stałe)
│   ├── signals.py              unieważnianie cache'u przy zapisie/usunięciu Linku
│   ├── forms.py                formularz webowy (adres + zwijane ustawienia zaawansowane)
│   ├── api_views.py / serializers.py / api_urls.py   REST API
│   ├── admin.py                rejestracja wszystkich trzech modeli w adminie
│   ├── templates/links/        szablony HTML renderowane po stronie serwera, dark mode domyślnie, bez frameworka JS
│   └── tests/                  80 testów w 7 plikach, jeden na obszar
├── benchmarks/locustfile.py    scenariusz obciążeniowy użyty do pomiaru przed/po
├── scripts/gen_prod_env.sh     generuje produkcyjny .env z .env.example na serwerze
├── docker-compose.yml          stos dev: bind mounty, porty wystawione do lokalnego debugowania
├── docker-compose.prod.yml     stos produkcyjny: bez bind mountów, Caddy jako jedyne wejście z zewnątrz
├── Caddyfile                   reverse proxy + konfiguracja automatycznego HTTPS
├── Dockerfile / entrypoint.sh  obraz aplikacji + punkt wejścia kontenera
├── .github/workflows/ci.yml    pipeline CI (lint + testy) i CD (deploy przez SSH)
├── requirements.txt / requirements-dev.txt   zależności produkcyjne / +linter+testy, rozdzielone
│                                             żeby obraz produkcyjny nie woził pytest/ruff
├── README.md / README.pl.md
└── LICENSE                     MIT
```

## Konfiguracja lokalna

Repozytorium nie zawiera żadnych prawdziwych sekretów. Skopiuj
`.env.example` do `.env` i uzupełnij dwie wartości istotne do lokalnego
developmentu:

1. **`SECRET_KEY`**: klucz kryptograficzny Django. Wygeneruj przez
   `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
   Unikaj `$` w wartości: Docker Compose robi własną interpolację
   `${VAR}` nad plikami `.env`, a `$` w wartości potrafi zostać cicho
   zinterpretowany jako zmienna (patrz
   [Rozwiązywanie problemów](#rozwiązywanie-problemów)).
2. **`IP_SALT`**: sól domieszana do każdego hashowanego adresu IP
   przed zapisem. Wygeneruj przez
   `python -c "import secrets; print(secrets.token_hex(32))"`. Musi
   pozostać stała w czasie (rotacja sprawia, że ten sam odwiedzający
   wygląda jak nowy) i nigdy nie może trafić do repo.

Reszta `.env.example` ma już działające wartości domyślne pod lokalnego
Dockera (`DB_HOST=db`, `REDIS_URL=redis://redis:6379/0` itd.) i nie
wymaga zmian, żeby stos ruszył. `DOMAIN` i `GEOIP_DB_PATH` są
opcjonalne. To, co odblokowują, opisano w komentarzach `.env.example`.

**Na serwerze** `scripts/gen_prod_env.sh <host-lub-domena>` generuje
kompletny produkcyjny `.env` jedną komendą (losowy `SECRET_KEY` i
`IP_SALT`, `DEBUG=False`, `ALLOWED_HOSTS` ustawiony na to, co podasz).

## Uruchomienie

**Wymagania:** Docker + Docker Compose. Nic więcej, nie trzeba lokalnie
instalować Pythona.

```bash
git clone https://github.com/jakubbak-online/skroclinka.pl.git
cd skroclinka.pl
cp .env.example .env      # uzupełnij SECRET_KEY i IP_SALT, patrz wyżej
docker compose up
```

Ta jedna komenda buduje obraz aplikacji, startuje Postgresa i Redisa,
nakłada migracje i `collectstatic` w jednorazowej usłudze `migrate`
(dzięki czemu `web`/`worker`/`beat` startują dopiero, gdy schemat
faktycznie istnieje, patrz
[Rozwiązywanie problemów](#rozwiązywanie-problemów), dlaczego to
osobna usługa, nie tylko skrypt startowy), i uruchamia serwer, workera
Celery i Celery Beat. Aplikacja stoi pod `http://localhost:8000/`.

Opcjonalnie: `docker compose exec web python manage.py createsuperuser`
pod dostęp do `/admin/`.

`docker-compose.prod.yml` to topologia użyta na prawdziwym
wdrożeniu: bez bind mountów (kod jest zapieczony w obrazie przy
buildzie, nie montowany na żywo z hosta), bez bezpośrednio wystawionych
portów Postgresa/Redisa, Caddy jako jedyny proces słuchający na 80/443.
Nie jest pomyślany do odpalenia lokalnie bez prawdziwej domeny: Let's
Encrypt weryfikuje własność domeny żywym żądaniem HTTP.

## Przegląd funkcji

Otwórz `http://localhost:8000/` (albo [skroclinka.pl](https://skroclinka.pl)):

1. **Wklej adres, dostaniesz krótki.** Domyślnie tylko pole adresu i
   przycisk.
2. **Rozwiń "Ustawienia zaawansowane"** po resztę: własny kod zamiast
   losowego, opcjonalne hasło, data wygaśnięcia, limit kliknięć.
   Wszystko opcjonalne i domyślnie zwinięte, bo większość linków tego
   nie potrzebuje.
3. **Kliknij krótki link.** Przekierowuje od razu (`302`). Jeśli ma
   hasło, najpierw zobaczysz mały formularz; poprawne hasło
   przekierowuje tak samo jak zwykły link, niepoprawne nie liczy się do
   limitu kliknięć ani do analityki.
4. **Wejdź na `/<kod>/stats/`** (link tuż pod krótkim adresem po
   utworzeniu) po dashboard: łączna liczba kliknięć, wykres dzienny (z
   `DailyStat`, nie z zapytania na żywo po surowych zdarzeniach) i
   tabela ostatnich kliknięć z urządzeniem/przeglądarką/systemem/skąd.
5. **Przełącz jasny/ciemny motyw** w prawym górnym rogu dowolnej
   strony. Ciemny jest domyślny, wybór zapamiętywany w `localStorage`.

## Testy

```bash
pip install -r requirements-dev.txt
pytest
```

W kontenerze: `docker compose exec web pytest`. Konfiguracja testowa
odpala zadania Celery synchronicznie (`CELERY_TASK_ALWAYS_EAGER`) i
podmienia produkcyjny hasher haseł oraz storage plików statycznych na
szybsze/prostsze odpowiedniki (patrz
[Rozwiązywanie problemów](#rozwiązywanie-problemów), dlaczego to
drugie jest koniecznością, nie tylko optymalizacją).

80 testów w 7 plikach, każdy dobrany pod to, co realnie sprawdza:
obsługa kolizji kodów (w tym wymuszona kolizja przez mock), każda
gałąź przekierowania (trafienie/pudło w cache, wygasły, nieaktywny,
hasło, limit kliknięć), unieważnianie cache'u przy edycji, progi rate
limitu i reset okna (przez `freezegun`, nie `time.sleep()`), agregacja
dzienna na 300 spreparowanych zdarzeniach łącznie z granicą dnia, wpływ
retencji na sumy historyczne, izolacja użytkowników w API.

Lint: `ruff check .` i `ruff format --check .`. Oba uruchamiane w CI
przy każdym pushu, razem z pytest, na prawdziwych kontenerach
Postgresa i Redisa, nie na mockach.

**Metodologia i wyniki benchmarku:** [Locust](https://locust.io)
(`benchmarks/locustfile.py`), scenariusz "50 użytkowników bije w ten
sam krótki link przez minutę", mediana i 95. percentyl czasu
odpowiedzi. Wersja sprzed cache'u, zapisująca synchronicznie, była
mierzona lokalnie na SQLite, zanim środowisko dockerowe było gotowe.
Sygnał był jasny mimo to: mediana wyglądała niewinnie (150 ms), ale 95.
percentyl sięgał kilku **sekund**, bo ogon rozkładu degraduje się pod
obciążeniem dużo wcześniej, niż widać to w samej średniej. Formalny,
jednakowy pomiar na prawdziwym stosie produkcyjnym (Postgres + Redis +
Celery, nie SQLite, który ma inny model blokad przy współbieżnych
zapisach) to kolejny punkt w [Planach na przyszłość](#plany-na-przyszłość).

## API

Pełny, interaktywny schemat pod
[`/api/docs/`](https://skroclinka.pl/api/docs/) (Swagger UI,
drf-spectacular). Skrót:

```
POST   /api/auth/token/         {username, password} -> {token}
GET    /api/links/              lista własnych linków, paginowana
POST   /api/links/               tworzy link
GET    /api/links/{code}/        szczegóły
PATCH  /api/links/{code}/        edycja
DELETE /api/links/{code}/        usunięcie
GET    /api/links/{code}/stats/  liczba kliknięć + ostatnie zdarzenia
```

Autoryzacja tokenem: `Authorization: Token <token>` w każdym żądaniu po
jego uzyskaniu. Każdy endpoint wymaga uwierzytelnienia (anonimowe
tworzenie linków jest funkcją formularza webowego, nie API, patrz
[Szczegóły komponentów](#szczegóły-komponentów)). Link, który istnieje,
ale należy do kogoś innego, zwraca `404`, tak samo jak link, który
nigdy nie powstał, nie `403`, co potwierdzałoby, że dany kod jest
zajęty.

## Szczegóły komponentów

<details>
<summary><strong>Rozwiń po opis komponent po komponencie, z linkami do kodu</strong></summary>

### 1. Modele ([`links/models.py`](links/models.py))

- **`Link`**: `owner` (nullable, anonimowe tworzenie linków jest
  zamierzone, patrz niżej), `code` (unikalny, indeksowany),
  `target_url`, `title`, `is_active`, `expires_at`, `max_clicks`,
  `password_hash`, `created_at`. Indeks na `(owner, -created_at)` pod
  listę "moich linków".
- **`ClickEvent`**: jeden wiersz na zapisane kliknięcie, `ip_hash`
  (nigdy surowy IP), `country`, `referer_domain`, `device_type`
  (desktop/mobile/tablet/**bot**), `browser`, `os`. Indeks na
  `(link, -created_at)`.
- **`DailyStat`**: `link`, `date`, `clicks`, `unique_visitors`, unique
  constraint na `(link, date)`, żeby `update_or_create` mogło być
  idempotentne.

`Link.owner` jest świadomie nullable: odejście od schematu, od którego
projekt wystartował. Projekt rate limitów wprost rozróżnia "tworzenie
linku (zalogowany)" od "tworzenie linku (anonim)" z dwoma różnymi
progami, więc anonimowe tworzenie linków musi realnie działać, nie tylko
być przypadkowo dopuszczone.

### 2. Logika biznesowa ([`links/services.py`](links/services.py))

Wszystko, co nie jest specyficzne dla HTTP, siedzi tutaj, dzięki temu
jest testowalne bez klienta i wielokrotnego użytku zarówno z widoku
webowego, jak i z REST API, bez duplikacji.

- **`create_link()`**: losuje 6-znakowy kod base62 (62⁶ ≈ 56 mld
  kombinacji) albo przyjmuje własny. Kolizje nie są zapobiegane
  sprawdzeniem `exists()` najpierw (to wyścig sprawdź-potem-zapisz przy
  równoległych żądaniach), tylko obsługiwane przez próbę zapisu i
  złapanie `IntegrityError` z unikalnego indeksu, jedynej rzeczy, która
  potrafi to rozstrzygnąć atomowo. Każda próba jest we własnym
  savepoincie `transaction.atomic()`; bez tego złapany `IntegrityError`
  zostawia **całą** otaczającą transakcję bezużyteczną, dopóki się jej
  nie zrolluje, nie tylko tę jedną próbę: błąd, który złapał własny
  zestaw testów tego projektu (patrz [Testy](#testy)).
- **`hash_ip()`**: `SHA-256(ip + IP_SALT)`. Sól siedzi w zmiennej
  środowiskowej celowo: sam wyciek bazy danych nie wystarczy do
  zbudowania przeciwko niej tęczowej tablicy.
- **`classify_device()`**: boty mają własną kategorię zamiast być
  wyrzucane albo liczone jako "desktop": ruch crawlerów potrafi
  przewyższyć liczbą realnych odwiedzających i inaczej cicho
  zniekształciłby każdy wykres.
- **`aggregate_daily_stats_for_date()`**: jedno zapytanie z
  `GROUP BY link_id` na dzień, obejmujące od razu wszystkie linki (nie
  pętla po linku), z wykluczeniem botów, zapisywane przez
  `update_or_create`, więc ponowne uruchomienie dla danego dnia
  nadpisuje, nie duplikuje.
- **`link_total_clicks()`**: sumuje `DailyStat.clicks` (przeżywa
  retencję) plus dzisiejsze, jeszcze niezagregowane `ClickEvent`, nie
  zwykłe `ClickEvent.objects.filter(link=link).count()`, które zaczęłoby
  cicho zaniżać wynik, gdy tylko ruszy czyszczenie po 90 dniach.

### 3. Widoki ([`links/views.py`](links/views.py))

- **`redirect_view`**: jedyny endpoint, dla którego powstał cały
  projekt. Sprawdzenie rate limitu, potem odczyt z cache'u
  (`link:{kod}`), Postgres tylko przy pudle, potem sprawdzenia
  `is_active`/`expires_at`/hasła/`max_clicks` na danych z cache'u, potem
  `record_click_task.delay()` (nieblokujące), potem
  `HttpResponseRedirect`, które Django domyślnie zwraca jako `302`.
  `302`, nie `301`: przekierowanie trwałe przeglądarka zapamiętuje na
  stałe i przestaje odpytywać serwer przy kolejnych wejściach,
  analityka przestaje liczyć, a zmieniony adres docelowy nigdy nie
  dotrze do osób, które już raz kliknęły.
- **`create_link_view`**: renderuje formularz, rate-limitowany osobno
  per użytkownik (zalogowany) albo per IP (anonim), z niższym progiem
  dla tych drugich.
- **`stats_view`**: czyta z `DailyStat` pod wykres, z surowego
  `ClickEvent` tylko pod tabelę "ostatnie kliknięcia", jedyne miejsce,
  gdzie zapytanie na żywo po surowych zdarzeniach faktycznie ma sens.

### 4. Zadania ([`links/tasks.py`](links/tasks.py))

Cienkie wrappery `@shared_task` nad funkcjami z `services.py`, nic
więcej. `record_click_task` parsuje z powrotem znacznik czasu (Celery
serializuje argumenty do JSON-a, który nie zna typu datetime) i woła
`services.record_click()`; `aggregate_daily_stats` i `purge_old_events`
to dwa nocne zadania, które Celery Beat odpala według harmonogramu
trzymanego w bazie danych (`django-celery-beat`), edytowalnego z panelu
admina bez redeployu.

### 5. Rate limiting ([`links/ratelimit.py`](links/ratelimit.py))

Własna implementacja na ~15 linijkach na Redisie (`INCR` + `EXPIRE`,
okno stałe), nie biblioteka: celowo, żeby pokazać zrozumienie
mechanizmu, nie tylko skonfigurowanie cudzego. Progi: 3 linki/h
anonimowo, 20/h zalogowany, 300 przekierowań/min per IP, wszędzie `429`
z `Retry-After`. Okno stałe ma znaną słabość (do ~2x limitu tuż przy
granicy okna); akceptowalne tutaj, bo celem jest powstrzymanie masowego
generowania linków i skanowania kodów, nie obrona przed precyzyjnie
zsynchronizowanym atakiem. Okno przesuwne albo token bucket
zamknęłyby tę lukę kosztem struktury posortowanego zbioru w Redisie
zamiast pojedynczego licznika.

### 6. Unieważnianie cache'u ([`links/signals.py`](links/signals.py))

Sygnały `post_save`/`post_delete` na `Link` kasują jego wpis w
cache'u. Wybrane zamiast jawnego wywołania z `services.py` właśnie
dlatego, że odpalają się też przy edycji z panelu admina albo z shella,
czego warstwa serwisów nigdy nie widzi.

### 7. REST API ([`links/api_views.py`](links/api_views.py), [`links/serializers.py`](links/serializers.py))

`ModelViewSet`, którego `get_queryset()` filtruje do
`Link.objects.filter(owner=request.user)`, zanim cokolwiek innego się
wykona, więc wbudowany w DRF `get_object()` po prostu nie znajduje
cudzego linku, bez żadnej własnej logiki odmowy dostępu, a zwrócony
`404` nie zdradza, czy dany kod w ogóle istnieje. Serializer zawsze woła
`services.create_link()`, nigdy `Link.objects.create()` wprost, więc API
dostaje za darmo to samo ponawianie przy kolizji i walidację
zastrzeżonych słów co formularz webowy.

### 8. Deployment (`Dockerfile`, `entrypoint.sh`, `docker-compose*.yml`, `Caddyfile`)

- **`entrypoint.sh`** jest celowo trywialny (`exec "$@"`): cała logika
  migracji/collectstatic siedzi w osobnej, jednorazowej usłudze
  `migrate`, na którą `web`/`worker`/`beat` czekają przez
  `depends_on: {condition: service_completed_successfully}`, patrz
  [Rozwiązywanie problemów](#rozwiązywanie-problemów) po błąd, który
  skłonił do wyciągnięcia tego z flagi startowej per usługa.
- **`docker-compose.prod.yml`** nie ma bind mountów (obraz jest
  przebudowywany, a kod kopiowany do niego przy deployu, nie montowany
  na żywo z hosta) i nie wystawia portów `db`/`redis` na hosta: Caddy
  jest jedynym procesem słuchającym na 80/443.
- **`Caddyfile`** czyta jedną zmienną środowiskową `DOMAIN` i załatwia
  resztę: wystawienie certyfikatu, jego odnawianie i przekierowanie
  HTTP→HTTPS oraz z subdomeny `www`, bez ręcznego `certbota`.

</details>

## Rozwiązywanie problemów

<details>
<summary><strong>Rozwiń po prawdziwe błędy znalezione podczas budowy i jak każdy z nich zdiagnozowano</strong></summary>

Żaden z poniższych nie jest hipotetyczny: każdy naprawdę się wydarzył
podczas budowy tego projektu, zapisane tu na wypadek, gdyby ten sam
rodzaj błędu wrócił.

**Ponawianie po kolizji, które działało ręcznie, a wysypywało się w
teście.** Pierwsza wersja `create_link()` łapała `IntegrityError` przy
kolizji kodu i po prostu ponawiała. Działało bez zarzutu przy ręcznym
klikaniu. Test wymuszający kolizję przez mock na `generate_code()`
wywalał się `TransactionManagementError` przy **drugiej** próbie:
niezłapany w odpowiedni sposób `IntegrityError` zostawia całą
otaczającą transakcję bezużyteczną, dopóki się jej nie zrolluje, nie
tylko nieudane zapytanie. Naprawa: każda próba we własnym savepoincie
`transaction.atomic()`, więc kolizja cofa tylko tę jedną próbę.

**`beat` w pętli restartów z `relation "django_celery_beat_..." does
not exist`.** Tylko usługa `web` nakładała migracje przy starcie, za
flagą środowiskową; `worker` i `beat` startowały równolegle bez
gwarancji, że schemat już istnieje, a `depends_on: {condition:
service_healthy}` na Postgresie dowodzi tylko, że *Postgres* odpowiada,
nie że migracje Django się nałożyły. Naprawa: migracje jako osobna,
jednorazowa usługa `migrate`, na której sukces czeka reszta przez
`condition: service_completed_successfully`, standardowy wzorzec
compose "odpal raz, przed startem reszty".

**Każda strona zwracająca `500` na produkcji, ale nie lokalnie.**
`docker-compose.prod.yml` celowo nie ma bind mountów, więc `migrate` i
`web` to osobne kontenery z niezależnymi, efemerycznymi systemami
plików. `collectstatic` (odpalony w `migrate`) zapisał swój manifest do
systemu plików, którego `web` nigdy nie widział, więc
`CompressedManifestStaticFilesStorage` nie miało czego odpytać, i
**każdy** tag `{% static %}` w szablonie bazowym rzucał `ValueError`.
Naprawa: nazwany wolumin Dockera (`staticfiles:`) dzielony między
`migrate` a `web`.

**CI padające na "Zainstaluj zależności", zanim ruff czy pytest w ogóle
się odpaliły.** `django-celery-beat==2.9.0` wymaga `Django<6.1`, a
projekt miał przypięte `Django==6.1`. Działało w długo żyjącym, lokalnym
venv (już zainstalowane pakiety nie są w pełni rewalidowane), ale nie
przy świeżej instalacji w CI. Za pierwszym błędem chował się drugi,
powiązany: `CompressedManifestStaticFilesStorage` wymaga, żeby
`collectstatic` już się wykonał, czego nic nie robi przed `pytest`, więc
każdy test dotykający szablonu też by padł. Naprawa: przypięcie
`Django==6.0.8` i zwykły `StaticFilesStorage` (bez manifestu)
specyficznie pod `IS_TESTING`. Oba znalezione lokalnie, w świeżym venv,
przed kolejnym pushem, nie z drugiego maila o failed CI.

**`docker compose up` wywalające się na `docker-credential-desktop:
executable file not found in %PATH%`, tylko w jednym terminalu.**
Okazało się to specyficzne dla środowiska Git Bash: PowerShell na tej
samej maszynie miał Dockera i jego credential helper w `PATH` bez
żadnych poprawek. Warto pamiętać na Windowsie: narzędzie "nie działa"
czasem znaczy "ten konkretny shell nie działa", nie samo narzędzie.

**Docker Compose po cichu psujące wartość z `.env`.** Wygenerowany
`SECRET_KEY` zawierał przypadkiem `$`. Compose robi własną
interpolację `${VAR}` nad plikami `.env` (nie tylko nad samym
`docker-compose.yml`), więc `$xyz` w wartości zostaje odczytane jako
"wartość zmiennej środowiskowej `xyz`", dając ostrzeżenie `"xyz"
variable is not set` i cicho ucięty sekret. Naprawa: nowa wartość bez
znaków specjalnych (`secrets.token_urlsafe`, same znaki alfanumeryczne
plus `-`/`_`).

</details>

## Bezpieczeństwo

| Zagrożenie | Wektor | Ryzyko | Jak zaadresowane w tym projekcie |
|---|---|---|---|
| Otwarte przekierowanie / phishing | Każdy może skierować krótki link pod dowolny adres | Średnie | Obecnie nic ponad walidację `URLField`; patrz [Plany na przyszłość](#plany-na-przyszłość) po planowany check Google Safe Browsing |
| Ekspozycja adresów IP | Analityka kliknięć z natury widzi IP odwiedzających | Wysokie przy niedbałej obsłudze | Nigdy nie zapisywany wprost, tylko hash SHA-256 z solą (sól w zmiennej środowiskowej, nie w repo); surowe zdarzenia kasowane po 90 dniach |
| Wyliczanie cudzych linków przez API | Zgadywanie kodu linku innego użytkownika | Niskie | Queryset filtrowany do `request.user` przed odczytem, więc cudzy link zwraca `404`, nie `403`, brak potwierdzenia, że kod jest zajęty |
| Masowe tworzenie linków / spam | Brak CAPTCHA na publicznym formularzu | Średnie | Rate limiting (3/h anonim, 20/h zalogowany) |
| Brute-force hasła do linku | Brak dedykowanej blokady prób hasła | Średnie | Pokryte ogólnym rate limitem endpointu przekierowania (300/min na IP), nie dedykowaną blokadą per link |
| Rozproszenie sekretów | `SECRET_KEY`, `IP_SALT`, dane do bazy żyją w `.env` | Wysokie przy wycieku | `.env` wszędzie gitignorowany; wartości produkcyjne generowane bezpośrednio na serwerze (`scripts/gen_prod_env.sh`), nigdy niecommitowane ani nieprzesyłane |
| Baza/cache wystawione do internetu | Mapowanie portów w Dockerze | Wysokie przy wystawieniu | Compose dev wystawia Postgresa/Redisa na hosta pod lokalne debugowanie; `docker-compose.prod.yml` nie wystawia żadnego z nich, tylko Caddy słucha na 80/443 |

## Plany na przyszłość

Świadomie zostawione na później: nic z tego nie blokowało pokazania
działającego, wdrożonego pipeline'u od początku do końca:

- **Prawdziwe liczby z benchmarku przed/po** na stosie produkcyjnym
  (Postgres + Redis + Celery), zastępujące obecne, wstępne liczby
  zmierzone na SQLite, teraz gdy cały stos jest realnie wdrażalny.
- **`DailyStat` kontra surowy `ClickEvent`, czas zapytania**, zmierzone
  obok siebie na prawdziwych danych, porównanie, na którym opiera się
  cały argument za tabelą agregatów.
- **Baza MaxMind GeoLite2** na serwerze; `lookup_country()` jest już
  napisane i bez niej łagodnie zwraca pusty string, dane o kraju po
  prostu się nie uzupełnią, dopóki plik `.mmdb` (wymaga darmowego konta
  MaxMind) nie trafi na miejsce.
- **Ochrona przed otwartym przekierowaniem**: sprawdzenie
  `target_url` w Google Safe Browsing przed aktywacją linku, plus strona
  pośrednia z ostrzeżeniem dla linków oznaczonych jako podejrzane.
- **Rate limiting z oknem przesuwnym albo token bucketem**, zamykający
  lukę na granicy okna, którą obecna implementacja z oknem stałym
  świadomie akceptuje.
- **Buforowany zapis kliknięć**: jedno zadanie Celery na kliknięcie
  jest proste i obecnie wystarczające; grupowanie zapisów w Redisie i
  zrzucanie ich co kilka sekund byłoby pierwszą rzeczą do zmiany przy
  istotnie większym ruchu.
- **Zrzut ekranu dashboardu** w tym README: teraz, gdy appka realnie
  działa, to już tylko formalność.

## Autor i licencja

Zbudowane przez [Jakuba Bąka](https://github.com/jakubbak-online).

Na licencji [MIT](LICENSE).
