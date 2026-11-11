"""Helpers for carrying a selected service through sign-in and registration."""

from urllib.parse import parse_qs, urlparse

from django.urls import reverse

from .models import Service


def active_service_from_slug(slug: str | None) -> Service | None:
    if not slug:
        return None
    return Service.objects.filter(slug=slug, is_active=True).first()


def active_service_from_next(next_url: str | None) -> Service | None:
    """Return the catalog's chosen service if `next` points at booking creation."""
    if not next_url:
        return None
    parsed = urlparse(next_url)
    if parsed.path != reverse("bookings:create"):
        return None
    slug = parse_qs(parsed.query).get("service", [None])[0]
    return active_service_from_slug(slug)
