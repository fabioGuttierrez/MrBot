from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth (allauth)
    path("accounts/", include("allauth.urls")),

    # Apps principais
    path("inbox/", include("apps.inbox.urls", namespace="inbox")),
    path("flows/", include("apps.flows.urls", namespace="flows")),
    path("bots/", include("apps.bots.urls", namespace="bots")),
    path("contacts/", include("apps.contacts.urls", namespace="contacts")),
    path("billing/", include("apps.billing.urls", namespace="billing")),
    path("dashboard/", include("apps.dashboard.urls", namespace="dashboard")),
    path("", include("apps.tenants.urls", namespace="tenants")),

    # Webhook UazAPI
    path("webhook/", include("apps.channels_wa.urls", namespace="channels_wa")),

    # Raiz → redireciona para inbox (sem conflito de namespace)
    path("", RedirectView.as_view(url="/inbox/", permanent=False)),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
