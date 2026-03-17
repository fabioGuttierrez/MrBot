from django.urls import path
from . import views

app_name = "contacts"

urlpatterns = [
    path("", views.index, name="index"),
    path("campaign/", views.campaign, name="campaign"),
    path("<uuid:contact_id>/", views.detail, name="detail"),
    path("<uuid:contact_id>/enrich/", views.enrich_contact, name="enrich"),
    path("<uuid:contact_id>/verify/", views.verify_number, name="verify"),
    path("<uuid:contact_id>/sync-labels/", views.sync_labels, name="sync_labels"),
]
