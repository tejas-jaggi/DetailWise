"""Persistent per-customer AI admission history, separate from booking data."""

from django.conf import settings
from django.db import models


class ExplanationQuota(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True,
        related_name="explanation_quota",
    )
    timestamps = models.JSONField(default=list)
