"""
Django base settings for MrBot SaaS.
"""
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "channels",
    "django_htmx",
    "crispy_forms",
    "crispy_tailwind",
    "django_celery_beat",
    "django_celery_results",
    "corsheaders",
    "allauth",
    "allauth.account",
]

LOCAL_APPS = [
    "apps.tenants",
    "apps.accounts",
    "apps.channels_wa",
    "apps.contacts",
    "apps.conversations",
    "apps.bots",
    "apps.flows",
    "apps.inbox",
    "apps.billing",
    "apps.dashboard",
    "apps.widget",
    "apps.bookings",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.tenants.context_processors.tenant",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Database — compatível com Supabase (PostgreSQL + SSL)
# --------------------------------------------------------------------------
_db_config = env.db("DATABASE_URL", default="postgres://mrbot:mrbot123@localhost:5432/mrbot")

# Supabase exige SSL. A URL do Supabase já inclui ?sslmode=require e o
# env.db() respeita isso. Para dev local (localhost) usamos "prefer"
# como fallback caso o sslmode não venha na URL.
if "OPTIONS" not in _db_config:
    _db_config["OPTIONS"] = {"sslmode": "prefer"}

# Mantém conexões abertas por N segundos (reduz overhead no Supabase/pooler).
_db_config["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

DATABASES = {"default": _db_config}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/inbox/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-allauth (>=65.x API)
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "none"  # mudar para 'mandatory' em produção

# --------------------------------------------------------------------------
# Channels (WebSocket)
# --------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL", default="redis://localhost:6379/0")],
        },
    },
}

# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Sao_Paulo"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Health-check de sessões WhatsApp: verifica e reconecta a cada 5 minutos
from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    "wa-session-health-check": {
        "task": "channels_wa.check_and_reconnect_sessions",
        "schedule": crontab(minute="*/5"),
    },
}

# --------------------------------------------------------------------------
# Redis (cache e sessions)
# --------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# --------------------------------------------------------------------------
# Static / Media
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --------------------------------------------------------------------------
# Internacionalização
# --------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Crispy Forms
# --------------------------------------------------------------------------
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_MODEL = "gpt-4o"

# --------------------------------------------------------------------------
# Evolution API (WhatsApp)
# --------------------------------------------------------------------------
EVOLUTION_API_URL = env("EVOLUTION_API_URL", default="http://localhost:8080")
EVOLUTION_API_KEY = env("EVOLUTION_API_KEY", default="")

# Retrocompatibilidade — removidos em versão futura
UAZAPI_BASE_URL = env("UAZAPI_BASE_URL", default=EVOLUTION_API_URL)
UAZAPI_GLOBAL_TOKEN = env("UAZAPI_GLOBAL_TOKEN", default=EVOLUTION_API_KEY)

# --------------------------------------------------------------------------
# MrBot config
# --------------------------------------------------------------------------
APP_BASE_URL = env("APP_BASE_URL", default="http://localhost:8000")
WEBHOOK_SECRET = env("WEBHOOK_SECRET", default="changeme")
MESSAGE_CONCAT_DELAY = 4  # segundos para aguardar msgs fragmentadas
