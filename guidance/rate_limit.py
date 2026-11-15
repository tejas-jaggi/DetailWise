"""Exact per-user sliding window, serialized by the primary database.

The write BEFORE the read is intentional: SQLite ignores select_for_update().
An UPDATE obtains a write lock on SQLite and a row lock on PostgreSQL. All
read/prune/admit/write work happens under that lock; model/network work does not.
"""

import math
import random
import time

from django.conf import settings
from django.db import DatabaseError, OperationalError, connection, transaction
from django.db.models import F
from django.db.models.functions import Now

from .models import ExplanationQuota


class RateLimitUnavailable(Exception):
    """Quota storage failed; do not bypass the gate and call the model."""


def _timestamp(row):
    # Database statement time AFTER acquiring the lock, shared by all workers.
    return row.checked_at.timestamp()


def _reserve(user_id, limit, window):
    with transaction.atomic():
        # Pin reads and writes to the same primary, even with replica routers.
        quotas = ExplanationQuota.objects.using("default")
        rows = quotas.filter(user_id=user_id)
        if not rows.update(timestamps=F("timestamps")):
            # SQLite's initial UPDATE locks even when no row exists. PostgreSQL
            # uses the unique user key to resolve simultaneous first creation;
            # UPDATE again to lock a row another transaction may have created.
            quotas.get_or_create(user_id=user_id)
            rows.update(timestamps=F("timestamps"))
        row = rows.annotate(checked_at=Now()).get()
        now = _timestamp(row)
        active = sorted(stamp for stamp in row.timestamps if stamp > now - window)
        if len(active) >= limit:
            # Also correct if an administrator lowered the configured limit.
            return max(1, math.ceil(active[len(active) - limit] + window - now))
        active.append(now)
        rows.update(timestamps=active)
    return 0


def reserve_explanation(user_id):
    """Reserve one request or return seconds until another request can be admitted.

    Denied requests do not add timestamps or extend the window. Reservations
    are not refunded for cache hits, model failures or disconnected clients.
    """
    policy = settings.GUIDANCE_RATE_LIMIT
    for attempt in range(6):
        try:
            return _reserve(user_id, policy["REQUESTS"], policy["WINDOW_SECONDS"])
        except OperationalError as exc:
            # Shared-cache SQLite tests and busy local development can fail fast
            # with SQLITE_LOCKED. Retry the entire rolled-back operation, bounded.
            if connection.vendor == "sqlite" and "locked" in str(exc).lower() and attempt < 5:
                time.sleep(random.uniform(0.01, 0.03) * (2 ** attempt))
                continue
            raise RateLimitUnavailable from exc
        except (DatabaseError, ExplanationQuota.DoesNotExist) as exc:
            raise RateLimitUnavailable from exc
