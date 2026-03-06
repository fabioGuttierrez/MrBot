from django.urls import path
from . import views

app_name = "inbox"

urlpatterns = [
    path("", views.index, name="index"),
    path("list/", views.conversation_list, name="list"),
    path("search/", views.search, name="search"),
    path("<uuid:conversation_id>/", views.conversation_detail, name="detail"),
    path("<uuid:conversation_id>/send/", views.send_message, name="send"),
    path("<uuid:conversation_id>/takeover/", views.takeover, name="takeover"),
    path("<uuid:conversation_id>/release/", views.release, name="release"),
    path("<uuid:conversation_id>/close/", views.close_conversation, name="close"),
]
