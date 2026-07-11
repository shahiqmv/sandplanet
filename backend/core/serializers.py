from rest_framework import serializers

from .models import (
    CompanyParameter,
    Holiday,
    ManpowerCategory,
    Site,
    User,
    UserSiteAllocation,
)


def can_view_contract_value(user, site):
    """Spec §2.3: Admin, HO roles, and the assigned Project PM only."""
    if user.is_ho:
        return True
    if user.role == User.Role.PM:
        pm = site.current_pm()
        return pm is not None and pm.id == user.id
    return False


class SiteSerializer(serializers.ModelSerializer):
    current_pm = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = [
            "id", "code", "name", "is_head_office", "scope",
            "contract_value", "currency",
            "award_date", "start_date", "duration_days",
            "planned_completion", "actual_completion", "status",
            "client_name", "client_address", "client_contact",
            "client_designation", "client_phone", "client_email",
            "consultant_name", "consultant_contact",
            "working_hours_from", "working_hours_to", "working_days",
            "current_pm",
        ]
        read_only_fields = ["status", "current_pm"]  # status via /status action only

    def get_current_pm(self, site):
        pm = site.current_pm()
        return {"id": pm.id, "full_name": pm.full_name} if pm else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and not can_view_contract_value(request.user, instance):
            data.pop("contract_value", None)
        return data

    def validate_code(self, value):
        # Immutable after first issued document (spec §2.1). No documents
        # module yet (M2) — until then, immutable after creation.
        if self.instance and value != self.instance.code:
            raise serializers.ValidationError(
                "Site code is immutable once the site exists."
            )
        return value


class AllocationSerializer(serializers.ModelSerializer):
    site_code = serializers.CharField(source="site.code", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = UserSiteAllocation
        fields = ["id", "user", "site", "site_code", "site_name", "from_date", "to_date"]


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    allocations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "email", "role", "is_active",
            "last_login", "password", "allocations", "must_change_password",
        ]
        read_only_fields = ["last_login", "is_active", "must_change_password"]

    def get_allocations(self, user):
        qs = user.site_allocations.filter(to_date__isnull=True).select_related("site")
        return AllocationSerializer(qs, many=True).data

    def create(self, validated_data):
        from .invites import make_temp_password

        password = validated_data.pop("password", None)
        temp = None
        if not password:  # invite flow — issue a temporary password to email
            temp = password = make_temp_password()
        user = User(**validated_data)
        user.set_password(password)
        user.must_change_password = bool(temp)
        user.save()
        user._temp_password = temp   # picked up by the viewset to email
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class ManpowerCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ManpowerCategory
        fields = ["id", "list_type", "grp", "name", "sort_order", "is_active"]


class ItemCategorySerializer(serializers.ModelSerializer):
    class Meta:
        from .models import ItemCategory

        model = ItemCategory
        fields = ["id", "name", "sort_order", "is_active"]


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "site", "day", "name"]


class ParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyParameter
        fields = ["key", "value", "description"]
