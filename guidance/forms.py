"""Input for the guidance endpoints: service, date and optional time (plan Task 7).

The error messages match the booking form and are fixed text, so they never
echo what the browser sent.
"""

from django import forms

from bookings.models import Service
from bookings.timeutils import central_now, is_past_central

PAST_DATE_MESSAGE = "Choose today or a later date (Central Time)."
# Same check and wording as bookings.forms.BookingForm (a test keeps them equal).
PAST_TIME_MESSAGE = "That time has already passed today. Choose a later time (Central Time)."


class GuidanceRequestForm(forms.Form):
    service = forms.ModelChoiceField(
        queryset=Service.objects.filter(is_active=True),
        error_messages={
            "required": "Choose a service.",
            "invalid_choice": "Select an available service.",
        },
    )
    date = forms.DateField(
        input_formats=["%Y-%m-%d"],
        error_messages={"required": "Choose a date.", "invalid": "Enter a valid date."},
    )
    time = forms.TimeField(
        required=False,
        input_formats=["%H:%M", "%H:%M:%S"],
        error_messages={"invalid": "Enter a valid time."},
    )

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date < central_now().date():
            raise forms.ValidationError(PAST_DATE_MESSAGE)
        return date

    def clean(self):
        """A time earlier than now on today's date is rejected, as in the booking form.

        A spring-forward time that does not exist is still accepted here: the
        facts then use daily values only (plan D9). The booking form rejects it on save.
        """
        cleaned = super().clean()
        date, time = cleaned.get("date"), cleaned.get("time")
        if date is not None and time is not None and is_past_central(date, time):
            self.add_error("time", PAST_TIME_MESSAGE)
        return cleaned

    def error_dict(self) -> dict:
        """``{field: [message, ...]}`` with the fixed messages only."""
        return {field: [str(message) for message in messages]
                for field, messages in self.errors.items()}
