"""Shared validation for staff reporting and exports."""

from django import forms


class BookingDateRangeForm(forms.Form):
    start_date = forms.DateField(
        required=False, label="From date", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"invalid": "Enter a valid start date (YYYY-MM-DD)."},
    )
    end_date = forms.DateField(
        required=False, label="Through date", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"invalid": "Enter a valid end date (YYYY-MM-DD)."},
    )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            self.add_error("end_date", "End date must be on or after start date.")
        return cleaned
