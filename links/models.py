from django.conf import settings
from django.db import models


class Link(models.Model):
    # Anonimowe tworzenie linków jest częścią projektu (osobne, niższe
    # limity ruchu dla niezalogowanych), więc właściciel nie zawsze istnieje.
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


class ClickEvent(models.Model):
    link = models.ForeignKey(Link, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(db_index=True)
    # Nie surowy IP — RODO traktuje go jako dane osobowe. Hash z solą
    # (settings.IP_SALT) wystarcza do liczenia unikalnych wejść w danym
    # dniu, a nie identyfikuje osoby.
    ip_hash = models.CharField(max_length=64)
    country = models.CharField(max_length=2, blank=True)
    referer_domain = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=20)  # desktop / mobile / tablet / bot
    browser = models.CharField(max_length=50, blank=True)
    os = models.CharField(max_length=50, blank=True)

    class Meta:
        indexes = [models.Index(fields=["link", "-created_at"])]

    def __str__(self):
        return f"{self.link.code} @ {self.created_at:%Y-%m-%d %H:%M}"
