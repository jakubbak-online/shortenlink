from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from links.api_views import LinkViewSet

router = DefaultRouter()
router.register("links", LinkViewSet, basename="link")

urlpatterns = router.urls + [
    # POST {"username", "password"} -> {"token": "..."} - do wklejenia
    # jako "Authorization: Token <token>" w kolejnych żądaniach.
    path("auth/token/", obtain_auth_token, name="api-token"),
]
