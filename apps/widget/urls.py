from django.urls import path
from . import views

app_name = "widget"

urlpatterns = [
    path("<slug:tenant_slug>/", views.widget_page, name="page"),
    path("<slug:tenant_slug>/embed.js", views.embed_js, name="embed_js"),
]
