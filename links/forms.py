from django import forms
from django.utils import timezone

from links.models import Link
from links.services import validate_custom_code


class LinkForm(forms.ModelForm):
    # Nie pola modelu wprost (custom_code nie mapuje się 1:1 na Link.code
    # — puste znaczy "wylosuj", password to surowy tekst, nie password_hash)
    # — deklarowane osobno, żeby kontrolować walidację i input_formats.
    custom_code = forms.CharField(
        required=False,
        label="Własny kod (opcjonalnie)",
        widget=forms.TextInput(attrs={"placeholder": "np. moja-promocja"}),
    )
    password = forms.CharField(
        required=False,
        label="Hasło (opcjonalnie)",
        widget=forms.PasswordInput(attrs={"placeholder": "zostaw puste, jeśli bez hasła"}),
    )
    expires_at = forms.DateTimeField(
        required=False,
        label="Wygasa (opcjonalnie)",
        # Przeglądarka z <input type="datetime-local"> wysyła
        # "2026-08-20T15:30" - domyślne DATETIME_INPUT_FORMATS Django tego
        # formatu (z "T") nie znają, więc trzeba go dopisać jawnie.
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    max_clicks = forms.IntegerField(
        required=False,
        min_value=1,
        label="Limit kliknięć (opcjonalnie)",
        widget=forms.NumberInput(attrs={"placeholder": "np. 100", "min": 1}),
    )

    class Meta:
        model = Link
        fields = ["target_url", "title", "custom_code", "expires_at", "max_clicks", "password"]
        labels = {
            "target_url": "Adres do skrócenia",
            "title": "Nazwa (opcjonalnie)",
        }
        widgets = {
            "target_url": forms.URLInput(attrs={"placeholder": "https://...", "autofocus": True}),
            "title": forms.TextInput(attrs={"placeholder": "np. link do CV"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Deklarowane pola (custom_code, password, ...) domyślnie
        # renderują się przed polami modelu z Meta - to jest kolejność
        # sensowniejsza dla użytkownika (adres najpierw).
        self.order_fields(["target_url", "title", "custom_code", "expires_at", "max_clicks", "password"])

    def clean_custom_code(self):
        code = self.cleaned_data.get("custom_code", "").strip()
        if not code:
            return ""
        try:
            validate_custom_code(code)
        except ValueError as exc:
            raise forms.ValidationError(str(exc))
        return code

    def clean_expires_at(self):
        value = self.cleaned_data.get("expires_at")
        if value and value <= timezone.now():
            raise forms.ValidationError("Data wygaśnięcia musi być w przyszłości.")
        return value
