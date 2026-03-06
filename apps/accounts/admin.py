from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, TenantMembership


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    readonly_fields = ("id", "date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        (_("Informações pessoais"), {"fields": ("first_name", "last_name", "phone", "avatar")}),
        (_("Permissões"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Datas"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "password1", "password2"),
        }),
    )


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "is_active", "created")
    list_filter = ("role", "is_active", "tenant")
    search_fields = ("user__email", "tenant__name")
    readonly_fields = ("id", "created", "modified")
    autocomplete_fields = ("user", "tenant")
