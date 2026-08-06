from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render

from links.forms import LinkForm
from links.models import Link
from links.services import create_link


def create_link_view(request):
    """Formularz tworzenia linku. Bez logowania — patrz docs/decisions.md."""
    short_link = None

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
            form = LinkForm()
    else:
        form = LinkForm()

    return render(request, "links/index.html", {"form": form, "short_link": short_link})


def redirect_view(request, code):
    """Przekierowanie pod docelowy URL.

    Na razie bez cache'u i bez zapisu analityki — to dochodzi w kolejnych
    etapach (patrz krotko-spec.md, sekcja 4.2 i 4.3).
    """
    try:
        link = Link.objects.get(code=code)
    except Link.DoesNotExist:
        raise Http404

    # HttpResponseRedirect = 302, celowo nie 301 — przeglądarka ma pytać
    # serwer za każdym razem, inaczej analityka i edycja URL-a przestają
    # działać dla osób, które już raz kliknęły. Patrz docs/decisions.md.
    return HttpResponseRedirect(link.target_url)
