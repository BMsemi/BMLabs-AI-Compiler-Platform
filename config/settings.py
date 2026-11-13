import os
import secrets
from pathlib import Path
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
# Explicit single-process Windows deployment through a loopback tunnel.
# Multi-worker/container deployments continue to require PostgreSQL and Redis.
SINGLE_HOST_DEPLOYMENT = os.getenv('BMLABS_SINGLE_HOST', '0') == '1'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY is required in production.')
    secret_path = BASE_DIR / '.local-secret'
    try:
        with secret_path.open('x') as handle:
            handle.write(secrets.token_urlsafe(64))
    except FileExistsError:
        pass
    SECRET_KEY = secret_path.read_text().strip()
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',')
CSRF_TRUSTED_ORIGINS = [v for v in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if v]
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8765').rstrip('/')
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'drf_spectacular', 'drf_spectacular_sidecar', 'accounts', 'organizations', 'projects',
    'compiler', 'builds', 'audit', 'core',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.SecurityHeadersMiddleware', 'audit.middleware.ActivityMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages', 'core.context.platform_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
database_url = os.getenv('DATABASE_URL', '')
if database_url:
    parsed = urlparse(database_url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise ImproperlyConfigured('DATABASE_URL must use PostgreSQL.')
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': unquote(parsed.path[1:]),
        'USER': unquote(parsed.username or ''), 'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname, 'PORT': parsed.port or 5432, 'CONN_MAX_AGE': 60}}
elif DEBUG or SINGLE_HOST_DEPLOYMENT or os.getenv('ALLOW_SQLITE_TESTS') == '1':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3',
        # Acquire the write reservation before transactional reads. The web app
        # and local compiler worker otherwise race while upgrading read locks.
        'OPTIONS': {'timeout': 30, 'transaction_mode': 'IMMEDIATE'}}}
else:
    raise ImproperlyConfigured('DATABASE_URL is required in production.')
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
PASSWORD_RESET_TIMEOUT = 3600
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Singapore'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'private-media'
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', '1') == '1'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'BM Labs <noreply@localhost>')
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# Enable only when the app is reachable exclusively through the trusted reverse proxy.
if os.getenv('TRUST_PROXY', '0') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
REDIS_URL = os.getenv('REDIS_URL', '')
if REDIS_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}}
else:
    if not DEBUG and not SINGLE_HOST_DEPLOYMENT and os.getenv('ALLOW_SQLITE_TESTS') != '1':
        raise ImproperlyConfigured('REDIS_URL is required for shared production throttling.')
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL or 'redis://localhost:6379/1')
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle', 'rest_framework.throttling.UserRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'anon': '60/hour', 'user': '1000/hour'},
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination', 'PAGE_SIZE': 30,
}
SPECTACULAR_SETTINGS = {'TITLE': 'BM Labs Compiler Platform API', 'VERSION': '1.0.0',
    'DESCRIPTION': 'Session-authenticated APIs. Bounded Linear int8 compilation through project builds. Unsafe requests require CSRF.',
    'SERVE_INCLUDE_SCHEMA': False, 'SWAGGER_UI_DIST': 'SIDECAR', 'SWAGGER_UI_FAVICON_HREF': 'SIDECAR'}
TOOLCHAIN = {name: os.getenv(name, '') for name in ['IVERILOG_PATH', 'VVP_PATH', 'YOSYS_PATH', 'ABC_PATH', 'NEXTPNR_PATH', 'FABULOUS_ROOT', 'X2_RTL_ROOT', 'AI_MODEL_ENDPOINT']}
COMPILER_MAX_ARTIFACT_BYTES = int(os.getenv('COMPILER_MAX_ARTIFACT_BYTES', str(128 * 1024 * 1024)))
COMPILER_ENABLED = os.getenv('COMPILER_ENABLED', '0') == '1'
COMPILER_MODEL_REPO = os.getenv('COMPILER_MODEL_REPO', '')
COMPILER_X1_REPO = os.getenv('COMPILER_X1_REPO', '')
COMPILER_PYTHON = os.getenv('COMPILER_PYTHON', '')
COMPILER_WSL_DISTRO = os.getenv('COMPILER_WSL_DISTRO', 'Ubuntu-22.04')
FABULOUS_RUNTIME = {
    'distro': os.getenv('FABULOUS_WSL_DISTRO', ''),
    'user': os.getenv('FABULOUS_WSL_USER', 'bmlabs'),
    'venv': os.getenv('FABULOUS_VENV', ''),
    'cad_bin': os.getenv('FABULOUS_CAD_BIN', ''),
}
FABULOUS_WORK_ROOT = os.getenv('FABULOUS_WORK_ROOT', '')
FABULOUS_HOST_STORAGE = os.getenv('FABULOUS_HOST_STORAGE', '')
PHYSICAL_TARGET_CONFIG = os.getenv('PHYSICAL_TARGET_CONFIG', str(BASE_DIR / 'deploy' / 'physical-target.json'))
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.getenv('LOG_LEVEL', 'INFO')}}
