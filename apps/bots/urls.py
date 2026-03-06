from django.urls import path
from . import views

app_name = "bots"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("<uuid:bot_id>/", views.detail, name="detail"),
    path("<uuid:bot_id>/toggle/", views.toggle, name="toggle"),
    path("<uuid:bot_id>/delete/", views.delete, name="delete"),
]
