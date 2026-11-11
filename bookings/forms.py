from django import forms

from .models import Booking, Service
from .timeutils import central_now, is_nonexistent_central, is_past_central


class BookingForm(forms.ModelForm):
    """Customer booking form: service, date and time only.

    The customer and price are never taken from the browser; the view sets
    the customer and the model snapshots the price.
    """

    service = forms.ModelChoiceField(
        queryset=Service.objects.filter(is_active=True),
        empty_label="Choose a service",
        error_messages={
            "required": "Choose a service.",
            "invalid_choice": "Select an available service.",
        },
    )

    class Meta:
        model = Booking
        fields = ["service", "date", "time"]
        labels = {"date": "Date", "time": "Time (Central Time)"}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        error_messages = {
            "date": {"required": "Choose a date.", "invalid": "Enter a valid date."},
            "time": {"required": "Choose a time.", "invalid": "Enter a valid time."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Browser hint only; the real check happens in clean().
        self.fields["date"].widget.attrs["min"] = central_now().date().isoformat()

    def clean(self):
        cleaned = super().clean()
        date, time = cleaned.get("date"), cleaned.get("time")
        if date is None or time is None:
            return cleaned

        now = central_now()
        if date < now.date():
            self.add_error("date", "Choose today or a later date (Central Time).")
        elif is_nonexistent_central(date, time):
            self.add_error(
                "time",
                "That time does not exist on this date because clocks move forward "
                "for daylight saving time. Choose another time.",
            )
        elif is_past_central(date, time, now=now):
            self.add_error(
                "time",
                "That time has already passed today. Choose a later time (Central Time).",
            )
        return cleaned
