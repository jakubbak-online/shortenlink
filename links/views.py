from django.core.cache import cache
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from links.forms import LinkForm
from links.models import Link
from links.services import create_link
from links.tasks import record_click_task
from links.utils import get_client_ip

CACHE_TTL = 3600


def create_link_view(request):
    """Formularz tworzenia linku. Bez logowania — tworzenie linku bez
    konta jest zamierzoną funkcją, nie przeoczeniem."""
    short_link = None
    short_code = None

    if request.method == "POST":
        form = LinkForm(request.POST)
        if form.is_valid():
            owner = request.user if request.user.is_authenticated else None
            link = create_link(
                owner=owner,
                target_url=form.cleaned_data["target_url"],
                title=form.cleaned_data["title"],
            )
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
    cache'u → sprawdzenie is_active/expires_at/max_clicks (limit liczony
    INCR-em w Redisie, nie COUNT(*) na ClickEvent — to policzenie byłoby
    dokładnie tym wolnym zapytaniem na krytycznej ścieżce, którego cały
    ten projekt ma unikać) → zapis kliknięcia w tle przez Celery (nie
    blokuje odpowiedzi) → 302.

    Etap 2 miał to wszystko synchronicznie w widoku — stąd benchmark
    "przed" w private/notatki.md. To jest wersja "po".
    """
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

    events = link.events.order_by("-created_at")
    context = {
        "link": link,
        "total_clicks": events.count(),
        "recent_events": events[:50],
    }
    return render(request, "links/stats.html", context)