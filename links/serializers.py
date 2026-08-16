from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import serializers

from links.models import ClickEvent, Link
from links.services import create_link, validate_custom_code


class ClickEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClickEvent
        fields = ["created_at", "device_type", "browser", "os", "country", "referer_domain"]


class LinkSerializer(serializers.ModelSerializer):
    short_url = serializers.SerializerMethodField()
    # custom_code i password nie mapują się 1:1 na pola modelu (code
    # generowany/wybierany raz przy tworzeniu, password to surowy tekst,
    # nie password_hash) - deklarowane osobno, tak jak w LinkForm.
    custom_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )
    max_clicks = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    class Meta:
        model = Link
        fields = [
            "code", "short_url", "target_url", "title", "is_active",
            "expires_at", "max_clicks", "created_at", "custom_code", "password",
        ]
        read_only_fields = ["code", "created_at"]

    def get_short_url(self, obj):
        request = self.context.get("request")
        path = f"/{obj.code}/"
        return request.build_absolute_uri(path) if request else path

    def validate_custom_code(self, value):
        if not value:
            return value
        try:
            validate_custom_code(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))
        return value

    def validate_expires_at(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Data wygaśnięcia musi być w przyszłości.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        custom_code = validated_data.pop("custom_code", "")
        password = validated_data.pop("password", "")
        try:
            # Zawsze przez create_link(), nigdy Link.objects.create()
            # wprost - to jedyne miejsce z retry na kolizję kodu i
            # walidacją RESERVED_CODES, ta sama funkcja co dla
            # formularza webowego.
            return create_link(
                owner=request.user,
                target_url=validated_data["target_url"],
                title=validated_data.get("title", ""),
                code=custom_code or None,
                password=password,
                expires_at=validated_data.get("expires_at"),
                max_clicks=validated_data.get("max_clicks"),
            )
        except ValueError as exc:
            # Zajęty własny kod wykryty dopiero przy zapisie (unikalny
            # indeks) - format i zastrzeżone słowa złapał już
            # validate_custom_code wyżej.
            raise serializers.ValidationError({"custom_code": [str(exc)]})

    def update(self, instance, validated_data):
        # Kod się nie zmienia po utworzeniu (zmiana kodu wysadziłaby już
        # rozesłane linki) - custom_code przy update jest po prostu
        # ignorowany, nie błędem, żeby PATCH z niezmienionym payloadem
        # z GET-a (który nie ma custom_code, ale mógłby mieć przez
        # nieuwagę) nie wywalał się bez potrzeby.
        validated_data.pop("custom_code", None)
        password = validated_data.pop("password", None)
        if password is not None:
            # Puste "password": "" w PATCH-u celowo zdejmuje hasło z
            # linku - to spójne z resztą API (klucz obecny w payloadzie
            # = ustaw na tę wartość, nieobecny = zostaw bez zmian).
            instance.password_hash = make_password(password) if password else ""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
