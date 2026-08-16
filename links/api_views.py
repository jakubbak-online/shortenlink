from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from links.models import Link
from links.serializers import ClickEventSerializer, LinkSerializer


class LinkViewSet(viewsets.ModelViewSet):
    """CRUD na linkach zalogowanego użytkownika + /stats/ dla pojedynczego
    linku. Adresowanie po `code`, nie po `id` — to ten sam identyfikator
    publiczny co w URL-u przekierowania, nie ma sensu mieć dwóch."""

    serializer_class = LinkSerializer
    lookup_field = "code"

    def get_queryset(self):
        # To jest cały mechanizm "cudzy link -> 404, nie 403": queryset
        # zawiera wyłącznie linki właściciela żądania, więc cudzy link
        # dla DRF-owego get_object() po prostu nie istnieje - normalny
        # Http404 z frameworka, bez własnej logiki permission_denied.
        # 403 zdradzałby, że obiekt istnieje, tylko nie dla tego usera.
        return Link.objects.filter(owner=self.request.user).order_by("-created_at")

    @action(detail=True, methods=["get"])
    def stats(self, request, code=None):
        link = self.get_object()
        events = link.events.order_by("-created_at")
        return Response(
            {
                "code": link.code,
                "total_clicks": events.count(),
                "recent_events": ClickEventSerializer(events[:50], many=True).data,
            }
        )
