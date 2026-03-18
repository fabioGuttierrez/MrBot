from django.urls import path
from . import views

app_name = "channels_wa"

urlpatterns = [
    # Gerenciamento de sessões — rotas fixas ANTES do catch-all do webhook
    path("sessions/",             views.sessions_list,        name="sessions"),
    path("sessions/reconnect/",   views.session_reconnect,    name="session_reconnect"),
    path("sessions/status/",      views.session_status,       name="session_status"),
    path("sessions/disconnect/",  views.session_disconnect,   name="session_disconnect"),
    path("sessions/pairing/",     views.session_pairing_code, name="session_pairing_code"),

    # Webhook receiver — catch-all por último
    path("<str:tenant_slug>/<str:instance_id>/", views.webhook_receiver, name="webhook"),
]
