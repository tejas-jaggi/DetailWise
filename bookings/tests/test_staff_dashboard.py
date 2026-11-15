"""Staff reports: aggregation, date boundaries, access control and safe CSV."""

import csv
import datetime
import io
import json
import re
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from bookings.models import Booking, Service
from bookings.reporting import booking_charts, booking_summary, spreadsheet_safe
from bookings.tests.test_time_validation import at_central, frozen

User = get_user_model()


class StaffDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user("staff", is_staff=True)
        cls.customer = User.objects.create_user("private-customer", email="private@example.com")
        cls.other = User.objects.create_user("another-customer")
        cls.exterior = Service.objects.get(slug="exterior-wash")
        cls.interior = Service.objects.get(slug="interior-clean")
        cls.past = Booking.objects.create(
            customer=cls.customer, service=cls.exterior,
            date=datetime.date(2026, 11, 9), time=datetime.time(10),
        )
        cls.started = Booking.objects.create(
            customer=cls.customer, service=cls.exterior,
            date=datetime.date(2026, 11, 10), time=datetime.time(15),
        )
        cls.upcoming = Booking.objects.create(
            customer=cls.other, service=cls.interior,
            date=datetime.date(2026, 11, 10), time=datetime.time(16),
        )
        cls.future = Booking.objects.create(
            customer=cls.customer, service=cls.exterior,
            date=datetime.date(2026, 11, 11), time=datetime.time(10),
            price_at_booking=Decimal("12.34"),
        )
        cls.cancelled = Booking.objects.create(
            customer=cls.other, service=cls.interior,
            date=datetime.date(2026, 11, 12), time=datetime.time(10),
            status=Booking.Status.CANCELLED,
        )

    def setUp(self):
        clock = frozen(at_central(2026, 11, 10, 15, 0))
        clock.start()
        self.addCleanup(clock.stop)
        self.client.force_login(self.staff)
        self.url = reverse("bookings:staff_dashboard")
        self.export_url = reverse("bookings:staff_export")

    def export(self, params=None):
        response = self.client.get(self.export_url, params or {})
        self.assertEqual(response.status_code, 200)
        text = b"".join(response.streaming_content).decode("utf-8-sig")
        return response, list(csv.reader(io.StringIO(text, newline="")))

    def test_staff_can_view_statistics(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["summary"], {
            "total": 5, "upcoming": 2, "cancelled": 1, "revenue": Decimal("142.34"),
        })
        self.assertContains(response, "$142.34")
        self.assertContains(response, "not collected payment")

    def test_revenue_uses_snapshot_not_current_service_price(self):
        Service.objects.update(price=Decimal("999.99"))
        self.assertEqual(self.client.get(self.url).context["summary"]["revenue"], Decimal("142.34"))

    def test_charts_group_by_appointment_date_and_service(self):
        charts = self.client.get(self.url).context["charts"]
        self.assertEqual(charts["trends"], [
            {"date": "2026-11-09", "count": 1}, {"date": "2026-11-10", "count": 2},
            {"date": "2026-11-11", "count": 1}, {"date": "2026-11-12", "count": 1},
        ])
        self.assertEqual(charts["popularity"], [
            {"service": "Exterior Wash", "count": 3}, {"service": "Interior Clean", "count": 2},
        ])

    def test_trend_axis_uses_sorted_discrete_dates_not_subday_ticks(self):
        script = Path(finders.find("js/staff-dashboard.js")).read_text(encoding="utf-8")
        axis = re.search(r'x: \{field: "date",(.*?)\n    y:', script, re.S).group(1)
        self.assertIn('type: "ordinal"', axis)
        self.assertIn('sort: "ascending"', axis)
        self.assertIn("utcFormat(toDate(datum.label), '%b %d, %Y')", axis)
        self.assertNotIn("tickCount", axis)
        self.assertNotIn('type: "temporal"', axis)

    def test_trends_have_one_row_per_full_date_across_years(self):
        Booking.objects.create(
            customer=self.customer, service=self.exterior,
            date=datetime.date(2027, 11, 10), time=datetime.time(9),
        )
        rows = self.client.get(self.url).context["charts"]["trends"]
        dates = [row["date"] for row in rows]
        self.assertEqual(dates, sorted(set(dates)))
        self.assertIn({"date": "2026-11-10", "count": 2}, rows)
        self.assertIn({"date": "2027-11-10", "count": 1}, rows)

    def test_date_ranges_match_dashboard_charts_and_export(self):
        cases = [
            ({}, 5, 2, 1, "142.34"),
            ({"start_date": "2026-11-10", "end_date": "2026-11-11"}, 3, 2, 0, "107.34"),
            ({"start_date": "2026-11-10", "end_date": "2026-11-10"}, 2, 1, 0, "95.00"),
            ({"start_date": "2026-11-11"}, 2, 1, 1, "12.34"),
            ({"end_date": "2026-11-09"}, 1, 0, 0, "35.00"),
            ({"start_date": "", "end_date": ""}, 5, 2, 1, "142.34"),
            ({"start_date": "2030-01-01"}, 0, 0, 0, "0.00"),
        ]
        for params, total, upcoming, cancelled, revenue in cases:
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.context["summary"], {
                    "total": total, "upcoming": upcoming, "cancelled": cancelled,
                    "revenue": Decimal(revenue),
                })
                charts = response.context["charts"]
                self.assertEqual(sum(row["count"] for row in charts["trends"]), total)
                self.assertEqual(sum(row["count"] for row in charts["popularity"]), total)
                _, rows = self.export(params)
                self.assertEqual(len(rows) - 1, total)

    def test_export_link_keeps_only_validated_filters(self):
        response = self.client.get(self.url, {
            "start_date": "2026-11-10", "end_date": "2026-11-11", "customer": self.customer.pk,
        })
        self.assertEqual(response.context["filter_query"], "start_date=2026-11-10&end_date=2026-11-11")
        self.assertContains(response, self.export_url + "?start_date=2026-11-10&amp;end_date=2026-11-11")

    def test_invalid_dates_return_400_without_report_or_export(self):
        cases = [
            {"start_date": "invalid"}, {"end_date": "2026-02-30"},
            {"start_date": "2026-11-12", "end_date": "2026-11-10"},
            {"start_date": "2026-11-10T12:00:00Z"}, {"end_date": "10000-01-01"},
            {"start_date": "2027-02-29"},
        ]
        for params in cases:
            for url in [self.url, self.export_url]:
                with self.subTest(params=params, url=url):
                    with mock.patch("bookings.staff_views.filtered_bookings") as query:
                        response = self.client.get(url, params)
                        query.assert_not_called()
                    self.assertContains(response, "Correct the date range", status_code=400)
                    self.assertNotIn("Content-Disposition", response)
                    self.assertNotContains(response, "dashboard-chart-data", status_code=400)

    def test_leap_day_and_extreme_valid_ranges(self):
        for date in ["2028-02-29", "0001-01-01", "9999-12-31"]:
            response = self.client.get(self.url, {"start_date": date, "end_date": date})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["summary"]["total"], 0)

    def test_empty_database_shows_zeroes_and_header_only_export(self):
        Booking.objects.all().delete()
        response = self.client.get(self.url)
        self.assertContains(response, "No bookings in this date range")
        self.assertEqual(response.context["summary"], {
            "total": 0, "upcoming": 0, "cancelled": 0, "revenue": Decimal("0.00"),
        })
        self.assertEqual(response.context["charts"], {"trends": [], "popularity": []})
        self.assertNotContains(response, "cdn.jsdelivr.net")
        self.assertEqual(len(self.export()[1]), 1)

    def test_all_cancelled_has_zero_revenue_and_upcoming(self):
        Booking.objects.update(status=Booking.Status.CANCELLED)
        self.assertEqual(self.client.get(self.url).context["summary"], {
            "total": 5, "upcoming": 0, "cancelled": 5, "revenue": Decimal("0.00"),
        })

    def test_inactive_service_history_is_retained(self):
        Service.objects.filter(pk=self.exterior.pk).update(is_active=False)
        self.assertContains(self.client.get(self.url), "Exterior Wash")
        self.assertEqual(len(self.export()[1]), 6)

    def test_upcoming_uses_central_date_when_utc_is_next_day(self):
        with frozen(at_central(2026, 11, 10, 23, 30)):
            self.assertEqual(self.client.get(self.url).context["summary"]["upcoming"], 1)

    def test_upcoming_matches_booking_rules_during_dst_transitions(self):
        Booking.objects.all().delete()
        for date, times, instants in [
            (datetime.date(2026, 11, 1), [datetime.time(1, 15), datetime.time(1, 30), datetime.time(2)], [
                datetime.datetime(2026, 11, 1, 6, 15, tzinfo=datetime.timezone.utc),
                datetime.datetime(2026, 11, 1, 7, 15, tzinfo=datetime.timezone.utc),
                datetime.datetime(2026, 11, 1, 8, 0, tzinfo=datetime.timezone.utc),
            ]),
            (datetime.date(2027, 3, 14), [datetime.time(1, 30), datetime.time(3), datetime.time(3, 30)], [
                at_central(2027, 3, 14, 1, 30), at_central(2027, 3, 14, 3, 0),
            ]),
        ]:
            Booking.objects.all().delete()
            for time in times:
                Booking.objects.create(customer=self.customer, service=self.exterior, date=date, time=time)
            for instant in instants:
                with self.subTest(instant=instant), frozen(instant):
                    expected = sum(not booking.is_past for booking in Booking.objects.all())
                    self.assertEqual(booking_summary(Booking.objects.all())["upcoming"], expected)

    def test_aggregations_use_three_queries_and_no_customer_join(self):
        with CaptureQueriesContext(connection) as queries:
            booking_summary(Booking.objects.all())
            booking_charts(Booking.objects.all())
        self.assertEqual(len(queries), 3)
        for query in queries:
            self.assertNotIn("accounts_user", query["sql"])

    def test_anonymous_redirected_with_next_and_customer_forbidden(self):
        for url in [self.url, self.export_url]:
            self.client.logout()
            response = self.client.get(url, {"start_date": "2026-11-10"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("accounts:login") + "?next="))
            self.assertIn("start_date", response.url)
            self.client.force_login(self.customer)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("Content-Disposition", response)

    def test_superuser_allowed_and_inactive_staff_denied(self):
        admin = User.objects.create_superuser("admin", password="unused-password")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(self.export_url).status_code, 200)
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.client.force_login(self.staff)
        for url in [self.url, self.export_url]:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_dashboard_navigation_only_visible_to_staff(self):
        response = self.client.get(self.url)
        self.assertContains(response, f'href="{self.url}" aria-current="page"')
        self.client.force_login(self.customer)
        self.assertNotContains(self.client.get(reverse("bookings:catalog")), self.url)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("bookings:catalog")), self.url)

    def test_reports_are_read_only_and_not_cached(self):
        before = list(Booking.objects.values())
        for url in [self.url, self.export_url]:
            response = self.client.get(url)
            if response.streaming:
                list(response.streaming_content)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("private", response["Cache-Control"])
            for method in ["post", "put", "patch", "delete"]:
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertEqual(list(Booking.objects.values()), before)

    def test_export_columns_values_order_and_snapshot(self):
        response, rows = self.export()
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="detailwise-bookings.csv"')
        self.assertEqual(rows[0], [
            "Reference", "Service", "Appointment date", "Appointment time (America/Chicago)",
            "Status", "Estimated price (USD)",
        ])
        self.assertEqual(rows[1], [self.past.reference, "Exterior Wash", "2026-11-09", "10:00:00", "saved", "35.00"])
        self.assertEqual(rows[-2][-1], "12.34")
        self.assertEqual(rows[-1][4], "cancelled")

    def test_no_customer_information_in_dashboard_or_export(self):
        html = self.client.get(self.url).content.decode()
        _, rows = self.export()
        for text in [html, str(rows)]:
            for private in [self.customer.username, self.other.username, self.customer.email]:
                self.assertNotIn(private, text)

    def test_csv_quotes_commas_quotes_newlines_and_preserves_unicode(self):
        name = 'Wash, "Deluxe"\nCafé 汽车'
        Service.objects.filter(pk=self.exterior.pk).update(name=name)
        _, rows = self.export()
        self.assertEqual(rows[1][1], name)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(len(row) == 6 for row in rows))

    def test_formula_injection_is_neutralized_in_export(self):
        for name in ['=1+1', '+SUM(1,2)', '-1+1', '@SUM(1,2)', '\t=1', '\r=1', '\n=1',
                     '   =1+1', '\ufeff=1+1', '\ufeff \ufeff=1+1', '\x00=1+1', '\u2003=1+1',
                     ' \t@SUM(1,2)', '＝1+1', '＋1+1', '－1+1', '＠SUM(1,2)']:
            with self.subTest(name=name):
                Service.objects.filter(pk=self.exterior.pk).update(name=name)
                _, rows = self.export()
                self.assertEqual(rows[1][1], "'" + name)
        self.assertEqual(spreadsheet_safe("Normal service"), "Normal service")

    def test_chart_data_and_table_escape_script_like_service_names(self):
        name = '</script><script>alert("x")</script>'
        Service.objects.filter(pk=self.exterior.pk).update(name=name)
        response = self.client.get(self.url)
        self.assertNotContains(response, name)
        html = response.content.decode()
        raw = html.split('<script id="dashboard-chart-data" type="application/json">')[1].split('</script>')[0]
        charts = json.loads(raw)
        self.assertEqual(charts["popularity"][0]["service"], name)
        self.assertContains(response, "&lt;/script&gt;")

    def test_csv_streams_with_one_query_regardless_of_row_count(self):
        response = self.client.get(self.export_url)
        with self.assertNumQueries(1):
            rows = list(response.streaming_content)
        self.assertEqual(len(rows), 7)  # BOM, header, five records.
