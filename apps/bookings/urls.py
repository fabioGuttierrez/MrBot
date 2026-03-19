from django.urls import path
from . import views

app_name = "bookings"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("upcoming/", views.upcoming_view, name="upcoming"),
    path("day/<str:date_str>/", views.day_detail, name="day_detail"),
    path("<uuid:booking_id>/status/<str:new_status>/", views.booking_update_status, name="update_status"),
    path("create/", views.booking_create, name="create"),
]
