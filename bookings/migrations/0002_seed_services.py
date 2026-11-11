"""Seed the three services from wireframe S01 (reversible)."""

from decimal import Decimal

from django.db import migrations

SERVICES = [
    {
        "slug": "exterior-wash",
        "name": "Exterior Wash",
        "description": "Exterior wash and dry for everyday surface dirt.",
        "price": Decimal("35.00"),
        "weather_sensitivity": "exterior",
        "display_order": 1,
    },
    {
        "slug": "interior-clean",
        "name": "Interior Clean",
        "description": "Vacuuming and cleaning of interior surfaces.",
        "price": Decimal("60.00"),
        "weather_sensitivity": "interior",
        "display_order": 2,
    },
    {
        "slug": "full-detail",
        "name": "Full Detail",
        "description": "Exterior wash plus interior cleaning in one package.",
        "price": Decimal("95.00"),
        "weather_sensitivity": "mixed",
        "display_order": 3,
    },
]


def seed_services(apps, schema_editor):
    Service = apps.get_model("bookings", "Service")
    for data in SERVICES:
        values = {key: value for key, value in data.items() if key != "slug"}
        Service.objects.update_or_create(slug=data["slug"], defaults=values)


def remove_services(apps, schema_editor):
    # Raises ProtectedError if bookings exist, which is the safe behavior.
    Service = apps.get_model("bookings", "Service")
    Service.objects.filter(slug__in=[s["slug"] for s in SERVICES]).delete()


class Migration(migrations.Migration):
    dependencies = [("bookings", "0001_initial")]

    operations = [migrations.RunPython(seed_services, remove_services)]
