import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)
PRODUCTION = os.getenv("DJANGO_ENV", "local") == "production"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or get_random_secret_key()
if PRODUCTION and not os.getenv("DJANGO_SECRET_KEY"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production")
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "drf_spectacular", "marketdata",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.debug",
                  "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
                  "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": os.getenv("PGDATABASE", "marketdata"),
    "USER": os.getenv("PGUSER", "postgres"), "PASSWORD": os.getenv("PGPASSWORD", ""),
    "HOST": os.getenv("PGHOST", "localhost"), "PORT": os.getenv("PGPORT", "5432"),
    "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True, "OPTIONS": {"connect_timeout": 5}}}
if os.getenv("MARKETDATA_SQLITE_TEST") == "1":
    if PRODUCTION:
        raise ImproperlyConfigured("SQLite test backend is forbidden in production")
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.getenv("MARKETDATA_SQLITE_PATH", str(BASE_DIR / "test.sqlite3"))}}
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication",
                   "rest_framework.authentication.BasicAuthentication"],
                  "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
                  "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination", "PAGE_SIZE": 100,
                  "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
                  "DEFAULT_THROTTLE_RATES": {"user": "1000/hour"},
                  "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema"}
SPECTACULAR_SETTINGS = {"TITLE": "Market Data API", "VERSION": "2.0", "SERVE_INCLUDE_SCHEMA": False}
SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.IsAuthenticated"]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
SECURE_HSTS_PRELOAD = PRODUCTION
X_FRAME_OPTIONS = "DENY"
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "formatters": {"json": {"()": "marketdata.logging.JsonFormatter"}},
           "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
           "loggers": {"marketdata": {"handlers": ["console"], "level": "INFO", "propagate": False}}}
EUREX_API_KEY = os.getenv("EUREX_API_KEY", "")
EUREX_QUERY_FILE = os.getenv("EUREX_QUERY_FILE", "")
LANGUAGE_CODE = "en-us"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MARKETDATA_RAW_ROOT = Path(os.getenv("MARKETDATA_RAW_ROOT", str(BASE_DIR / "raw_data")))
MARKETDATA_EXPORT_ROOT = Path(os.getenv("MARKETDATA_EXPORT_ROOT", str(BASE_DIR / "exports")))
