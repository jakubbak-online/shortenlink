from django import forms

from links.models import Link


class LinkForm(forms.ModelForm):
    class Meta:
        model = Link
        fields = ["target_url", "title"]
        labels = {
            "target_url": "Adres do skrócenia",
            "title": "Nazwa (opcjonalnie)",
        }
        widgets = {
            "target_url": forms.URLInput(attrs={"placeholder": "https://...", "autofocus": True}),
            "title": forms.TextInput(attrs={"placeholder": "np. link do CV"}),
        }
