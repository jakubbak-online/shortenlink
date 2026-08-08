from django.urls import path

from links import views

app_name = "links"

urlpatterns = [
    path("", views.create_link_view, name="create"),
    path("<str:code>/stats/", views.stats_view, name="stats"),
    # Musi być ostatni — inaczej przechwyci /admin/, /api/ itd.
    path("<str:code>/", views.redirect_view, name="redirect"),
]
