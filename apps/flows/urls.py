from django.urls import path
from . import views

app_name = "flows"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.builder, name="new"),
    path("<uuid:flow_id>/", views.builder, name="builder"),
    path("<uuid:flow_id>/save/", views.save_flow, name="save"),
    path("<uuid:flow_id>/toggle/", views.toggle_active, name="toggle"),
    path("<uuid:flow_id>/delete/", views.delete_flow, name="delete"),
]
