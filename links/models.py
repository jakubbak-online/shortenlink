from django.conf import settings
from django.db import models


class Link(models.Model):
    # Anonimowe tworzenie linków jest częścią projektu (patrz limity ruchu
    # w docs/decisions.md), więc właściciel nie zawsze istnieje.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="links",
        null=True,
        blank=True,
    )
    code = models.CharField(max_length=16, unique=True, db_index=True)
    target_url = models.URLField(max_length=2048)
    title = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    max_clicks = models.PositiveIntegerField(null=True, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self):
        return self.code
