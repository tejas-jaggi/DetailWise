"""Central Time helpers.

DetailWise operates in Urbana, IL, so every appointment date and time is
interpreted as Central Time (America/Chicago), whatever the server's own
time zone is.
"""

import datetime
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")


def combine_central(date: datetime.date, time: datetime.time) -> datetime.datetime:
    """Return the appointment as a timezone-aware Central Time datetime.

    For the repeated hour when clocks fall back (e.g. 1:30 AM on the first
    Sunday of November), `fold=0` picks the first occurrence (CDT).
    """
    return datetime.datetime.combine(date, time).replace(tzinfo=CENTRAL, fold=0)


def central_now() -> datetime.datetime:
    """The current moment, expressed in Central Time."""
    from django.utils import timezone

    return timezone.now().astimezone(CENTRAL)


def is_nonexistent_central(date: datetime.date, time: datetime.time) -> bool:
    """True for wall-clock times skipped when clocks spring forward.

    Example: 2:30 AM on the second Sunday of March never happens in Central
    Time. A round trip through UTC changes such a time, which reveals it.
    """
    local = combine_central(date, time)
    round_trip = local.astimezone(datetime.timezone.utc).astimezone(CENTRAL)
    return round_trip.replace(tzinfo=None) != local.replace(tzinfo=None)


def is_past_central(
    date: datetime.date,
    time: datetime.time,
    now: datetime.datetime | None = None,
) -> bool:
    """True if the appointment is at or before `now` (default: current time).

    Compares complete, timezone-aware datetimes, so a same-day time that has
    already passed counts as past.

    Both values are converted to UTC first. Python compares two datetimes that
    share a tzinfo object by wall-clock time alone, which is wrong in the
    repeated fall-back hour: 1:30 AM CDT (06:30 UTC) is earlier than 1:15 AM
    CST (07:15 UTC), even though 1:30 looks later.
    """
    current = now if now is not None else central_now()
    utc = datetime.timezone.utc
    return combine_central(date, time).astimezone(utc) <= current.astimezone(utc)
