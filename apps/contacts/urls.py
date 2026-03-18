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
    # Broadcast
    path("broadcast/", views.broadcast_list, name="broadcast_list"),
    path("broadcast/create/", views.broadcast_create, name="broadcast_create"),
    # Pipeline Kanban
    path("pipeline/", views.pipeline, name="pipeline"),
    path("<uuid:contact_id>/stage/", views.update_stage, name="update_stage"),
    # Follow-ups
    path("followups/", views.followup_list, name="followup_list"),
    path("followups/create/", views.followup_create, name="followup_create"),
    path("followups/<uuid:followup_id>/cancel/", views.followup_cancel, name="followup_cancel"),
]
