from django.urls import path
from . import views

app_name = "channels_wa"

urlpatterns = [
    path("<str:tenant_slug>/<str:instance_id>/", views.webhook_receiver, name="webhook"),
]
