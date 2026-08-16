from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("links.api_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
    # links.urls jest ostatnie — kończy się złapaniem-wszystkiego pod
    # <code>/, więc musi być routowane po /admin/ i /api/.
    path("", include("links.urls")),
]
