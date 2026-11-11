from django.contrib import admin

from .models import Booking, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "weather_sensitivity", "is_active", "display_order")
    list_editable = ("is_active", "display_order")
    list_filter = ("is_active", "weather_sensitivity")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "service", "date", "time", "status", "price_at_booking")
    list_filter = ("status", "service", "date")
    search_fields = ("customer__username",)
    readonly_fields = ("price_at_booking", "created_at", "updated_at")
    date_hierarchy = "date"
    list_select_related = ("customer", "service")

    @admin.display(description="Reference", ordering="pk")
    def reference(self, obj):
        return obj.reference
