from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone

from links.forms import LinkForm
from links.models import Link
from links.services import create_link, record_click
from links.utils import get_client_ip


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
    """Przekierowanie pod docelowy URL.

    Etap 2: zapis kliknięcia dzieje się tutaj, synchronicznie, przed
    zwróceniem odpowiedzi — to jest wersja "na razie źle", zostawiona
    specjalnie jako punkt odniesienia do benchmarku przed/po. Cache i
    przeniesienie zapisu do kolejki dochodzą w etapie 3.
    """
    try:
        link = Link.objects.get(code=code)
    except Link.DoesNotExist:
        raise Http404

    record_click(
        link_id=link.id,
        ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        referer=request.META.get("HTTP_REFERER", ""),
        timestamp=timezone.now(),
    )

    # HttpResponseRedirect = 302, celowo nie 301 — przeglądarka ma pytać
    # serwer za każdym razem, inaczej ten zapis wyżej nigdy by się nie
    # wykonał dla powracających wejść, a zmiana target_url nie dotarłaby
    # do osób, które już raz kliknęły.
    return HttpResponseRedirect(link.target_url)


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