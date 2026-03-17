from django.urls import path
from . import views

app_name = "tenants"

urlpatterns = [
    path("onboarding/", views.onboarding, name="onboarding"),
    path("onboarding/create/", views.onboarding_create_tenant, name="onboarding_create_tenant"),
    path("onboarding/wa/connect/", views.onboarding_wa_connect, name="onboarding_wa_connect"),
    path("onboarding/wa/status/", views.onboarding_wa_status, name="onboarding_wa_status"),
]
