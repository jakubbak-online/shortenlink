from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from links.forms import LinkForm
from links.models import Link
from links.ratelimit import RateLimitExceeded, check_rate_limit
from links.services import create_link, link_total_clicks
from links.tasks import record_click_task
from links.utils import get_client_ip

CACHE_TTL = 3600

# Progi z sekcji 4.4 specyfikacji. Tworzenie linku anonimowo ma niższy
# limit niż zalogowany, ale wciąż działa - anonimowe tworzenie linków
# jest zamierzoną funkcją, nie przeoczeniem (patrz Link.owner nullable).
RATE_LIMIT_CREATE_ANONYMOUS = 3  # na godzinę, per IP
RATE_LIMIT_CREATE_AUTHENTICATED = 20  # na godzinę, per użytkownik
RATE_LIMIT_REDIRECT_PER_IP = 300  # na minutę


def _rate_limited_response(exc: RateLimitExceeded) -> HttpResponse:
    response = HttpResponse("Za dużo żądań, spróbuj ponownie później.", status=429)
    response["Retry-After"] = str(exc.retry_after)
    return response


def create_link_view(request):
    """Formularz tworzenia linku. Bez logowania — tworzenie linku bez
    konta jest zamierzoną funkcją, nie przeoczeniem."""
    short_link = None
    short_code = None

    if request.method == "POST":
        owner = request.user if request.user.is_authenticated else None
        if owner:
            limit_key = f"ratelimit:create:user:{owner.id}"
            limit = RATE_LIMIT_CREATE_AUTHENTICATED
        else:
            limit_key = f"ratelimit:create:ip:{get_client_ip(request)}"
            limit = RATE_LIMIT_CREATE_ANONYMOUS
        try:
            check_rate_limit(limit_key, limit=limit, window_seconds=3600)
        except RateLimitExceeded as exc:
            return _rate_limited_response(exc)

        form = LinkForm(request.POST)
        if form.is_valid():
            try:
                link = create_link(
                    owner=owner,
                    target_url=form.cleaned_data["target_url"],
                    title=form.cleaned_data["title"],
                    code=form.cleaned_data["custom_code"] or None,
                    password=form.cleaned_data["password"],
                    expires_at=form.cleaned_data["expires_at"],
                    max_clicks=form.cleaned_data["max_clicks"],
                )
            except ValueError as exc:
                # Kolizja własnego kodu wykryta dopiero przy zapisie
                # (unikalny indeks) - clean_custom_code złapał już format
                # i zastrzeżone słowa wcześniej, to tylko zajętość.
                form.add_error("custom_code", str(exc))
            else:
                short_link = request.build_absolute_uri(f"/{link.code}/")
                short_code = link.code
                form = LinkForm()
    else:
        form = LinkForm()

    context = {"form": form, "short_link": short_link, "short_code": short_code}
    return render(request, "links/index.html", context)


def redirect_view(request, code):
    """Przekierowanie pod docelowy URL — ścieżka, dla której powstał cały
    projekt.

    Kolejność: cache Redis (`link:{code}`) → miss: Postgres + zapis do
    cache'u → sprawdzenie is_active/expires_at → (jeśli jest hasło:
    formularz, dalej dopiero po poprawnym haśle) → max_clicks (limit
    liczony INCR-em w Redisie, nie COUNT(*) na ClickEvent — to policzenie
    byłoby dokładnie tym wolnym zapytaniem na krytycznej ścieżce, którego
    cały ten projekt ma unikać) → zapis kliknięcia w tle przez Celery (nie
    blokuje odpowiedzi) → 302.

    Etap 2 miał to wszystko synchronicznie w widoku — stąd benchmark
    "przed" w private/notatki.md. To jest wersja "po".
    """
    try:
        check_rate_limit(
            f"ratelimit:redirect:ip:{get_client_ip(request)}",
            limit=RATE_LIMIT_REDIRECT_PER_IP,
            window_seconds=60,
        )
    except RateLimitExceeded as exc:
        return _rate_limited_response(exc)

    cache_key = f"link:{code}"
    data = cache.get(cache_key)

    if data is None:
        try:
            link = Link.objects.get(code=code)
        except Link.DoesNotExist:
            raise Http404
        data = {
            "id": link.id,
            "target_url": link.target_url,
            "is_active": link.is_active,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "max_clicks": link.max_clicks,
            "password_hash": link.password_hash,
        }
        # Sygnały w signals.py kasują ten klucz przy zapisie/usunięciu
        # Linku, więc TTL tutaj jest tylko siatką bezpieczeństwa (np. na
        # wypadek unieważnienia, które się nie wykonało), nie głównym
        # mechanizmem świeżości danych.
        cache.set(cache_key, data, timeout=CACHE_TTL)

    if not data["is_active"]:
        raise Http404

    if data["expires_at"] and timezone.now() >= parse_datetime(data["expires_at"]):
        raise Http404

    if data["password_hash"]:
        # Sam widok formularza z hasłem nie liczy się jako kliknięcie —
        # ani do max_clicks, ani do analityki. Dopiero poprawne hasło
        # kończy się w _finish_redirect, dokładnie tak samo jak link bez
        # hasła.
        error = None
        if request.method == "POST":
            if check_password(request.POST.get("password", ""), data["password_hash"]):
                return _finish_redirect(request, code, data)
            error = "Nieprawidłowe hasło."
        return render(request, "links/password.html", {"error": error})

    return _finish_redirect(request, code, data)


def _finish_redirect(request, code, data):
    if data["max_clicks"] is not None:
        counter_key = f"clicks:{code}"
        # add() ustawia 0 tylko jeśli klucza jeszcze nie ma (atomowo, bez
        # wyścigu) — potem incr() jest atomowym INCR-em Redisa. To
        # standardowy wzorzec liczników w cache Django, bezpieczny przy
        # równoległych żądaniach na ten sam link.
        cache.add(counter_key, 0)
        clicks_so_far = cache.incr(counter_key)
        if clicks_so_far > data["max_clicks"]:
            raise Http404

    record_click_task.delay(
        link_id=data["id"],
        ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        referer=request.META.get("HTTP_REFERER", ""),
        timestamp=timezone.now().isoformat(),
    )

    # HttpResponseRedirect = 302, celowo nie 301 — przeglądarka ma pytać
    # serwer za każdym razem, inaczej powyższe sprawdzenia i zapis
    # kliknięcia nigdy by się nie wykonały dla powracających wejść, a
    # zmiana target_url nie dotarłaby do osób, które już raz kliknęły.
    return HttpResponseRedirect(data["target_url"])


def stats_view(request, code):
    try:
        link = Link.objects.get(code=code)
    except Link.DoesNotExist:
        raise Http404

    # Wykres/tabela dzienna z DailyStat (agregat, szybkie) - nie z
    # ClickEvent (surowe zdarzenia, wolne przy dużej historii i znikają
    # po 90 dniach). Lista "ostatnie kliknięcia" niżej jest jedynym
    # miejscem, gdzie nadal czytamy ClickEvent wprost - to podgląd na
    # żywo, nie coś, co ma sens trzymać wiecznie zagregowane.
    daily_stats = link.daily_stats.order_by("-date")[:30]
    recent_events = link.events.order_by("-created_at")[:50]

    context = {
        "link": link,
        "total_clicks": link_total_clicks(link),
        "daily_stats": daily_stats,
        # Do wykresu: chronologicznie (najstarszy pierwszy), same proste
        # typy - json_script w szablonie nie ugryzie QuerySet/date wprost.
        "daily_stats_chart": [
            {"date": stat.date.isoformat(), "clicks": stat.clicks}
            for stat in reversed(daily_stats)
        ],
        "recent_events": recent_events,
    }
    return render(request, "links/stats.html", context)