from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase

from bookings.models import Service

EXPECTED = [
    ("exterior-wash", "Exterior Wash", Decimal("35.00"), "exterior",
     "Exterior wash and dry for everyday surface dirt."),
    ("interior-clean", "Interior Clean", Decimal("60.00"), "interior",
     "Vacuuming and cleaning of interior surfaces."),
    ("full-detail", "Full Detail", Decimal("95.00"), "mixed",
     "Exterior wash plus interior cleaning in one package."),
]


class SeedServicesTests(TestCase):
    """The test database is built by running every migration, seed included."""

    def test_three_services_seeded_in_display_order(self):
        services = list(Service.objects.all())
        self.assertEqual(
            [(s.slug, s.name, s.price, s.weather_sensitivity, s.description) for s in services],
            EXPECTED,
        )

    def test_seeded_services_are_active(self):
        self.assertEqual(Service.objects.filter(is_active=True).count(), 3)


class SeedMigrationReversibilityTests(TransactionTestCase):
    serialized_rollback = True  # restore seed data for any later tests

    def test_seed_migration_reverses_and_reapplies(self):
        call_command("migrate", "bookings", "0001", verbosity=0)
        self.assertEqual(Service.objects.count(), 0)
        call_command("migrate", "bookings", verbosity=0)
        self.assertEqual(Service.objects.count(), 3)
