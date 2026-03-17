from .base import *  # noqa

DEBUG = True

INSTALLED_APPS += [
    "debug_toolbar",
    "django_extensions",
]

MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

INTERNAL_IPS = ["127.0.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Sem Redis em dev local: usa LocMemCache (cache) e DB (sessões)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

DEBUG_TOOLBAR_CONFIG = {"INTERCEPT_REDIRECTS": False}

DEBUG_TOOLBAR_PANELS = [
    "debug_toolbar.panels.history.HistoryPanel",
    "debug_toolbar.panels.versions.VersionsPanel",
    "debug_toolbar.panels.timer.TimerPanel",
    "debug_toolbar.panels.settings.SettingsPanel",
    "debug_toolbar.panels.headers.HeadersPanel",
    "debug_toolbar.panels.request.RequestPanel",
    "debug_toolbar.panels.sql.SQLPanel",
    "debug_toolbar.panels.staticfiles.StaticFilesPanel",
    "debug_toolbar.panels.templates.TemplatesPanel",
    "debug_toolbar.panels.cache.CachePanel",
    "debug_toolbar.panels.signals.SignalsPanel",
    "debug_toolbar.panels.logging.LoggingPanel",
]
