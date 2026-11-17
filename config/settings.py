import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

TESTING = 'test' in sys.argv or 'pytest' in sys.argv

DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

# SECRET_KEY must come from the environment in production. Failing to set one
# is a deployment error, not something we paper over with a weak default.
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'dev-only-change-me'
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY must be set in the environment (or .env) when DEBUG=False.')
ALLOWED_HOSTS = [x.strip() for x in os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if x.strip()]
<<<<<<< HEAD
for _d in ('.ngrok-free.app', '.ngrok-free.dev', '.ngrok.io'):
    if _d not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_d)

CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]
for _o in ('https://*.ngrok-free.app', 'https://*.ngrok-free.dev', 'https://*.ngrok.io'):
    if _o not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_o)

# If an ngrok callback base URL is configured, automatically trust its host and CSRF origin
_ngrok_base = os.getenv('MPESA_CALLBACK_BASE_URL', '').strip().rstrip('/')
if _ngrok_base:
    if '://' in _ngrok_base:
        _ngrok_host = _ngrok_base.split('://', 1)[1].split('/', 1)[0].split(':')[0]
    else:
        _ngrok_host = _ngrok_base.split('/', 1)[0].split(':')[0]
    if _ngrok_host and _ngrok_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_ngrok_host)
    _proto = 'https://' if not _ngrok_base.startswith('http://') else 'http://'
    _origin = f"{_proto}{_ngrok_host}"
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
=======
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'store',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'store.context_processors.store_context',
            'store.context_processors.manage_nav',
        ],
    },
}]

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE') or 'django.db.backends.sqlite3',
        'NAME': os.getenv('DB_NAME') or BASE_DIR / 'db.sqlite3',
        'USER': os.getenv('DB_USER', ''),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', ''),
        'PORT': os.getenv('DB_PORT', ''),
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': (
        'whitenoise.storage.CompressedManifestStaticFilesStorage'
        if not DEBUG and not TESTING else
        'django.contrib.staticfiles.storage.StaticFilesStorage'
    )},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/account/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

<<<<<<< HEAD
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '').strip()
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))

default_from = os.getenv('DEFAULT_FROM_EMAIL', '').strip()
if not default_from or 'your-email@' in default_from:
    if EMAIL_HOST_USER:
        DEFAULT_FROM_EMAIL = f"Reeves Boutique <{EMAIL_HOST_USER}>"
    else:
        DEFAULT_FROM_EMAIL = 'no-reply@reevesboutique.local'
else:
    DEFAULT_FROM_EMAIL = default_from

# When DEBUG is True and no SMTP credentials are provided, use the console backend
if DEBUG and not EMAIL_HOST_USER:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'store.email_backend.DatabaseSMTPEmailBackend'
=======
EMAIL_BACKEND = 'store.email_backend.DatabaseSMTPEmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() == 'true'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL') or EMAIL_HOST_USER or 'no-reply@reevesboutique.local'
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

# Security hardening (enabled automatically when DEBUG=False)
SECURE_SSL_REDIRECT = not DEBUG and os.getenv('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
SESSION_COOKIE_SECURE = not DEBUG and os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
CSRF_COOKIE_SECURE = not DEBUG and os.getenv('CSRF_COOKIE_SECURE', 'True').lower() == 'true'
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True

# Bound uploads (media files are validated again in store.services; these cap
# the request body and memory footprint before a view ever runs).
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SILENCED_SYSTEM_CHECKS = [] if DEBUG else ['security.W019']

LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
        'simple': {'format': '{levelname} {asctime} {message}', 'style': '{'},
    },
    'filters': {'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}},
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'file': {'class': 'logging.handlers.RotatingFileHandler', 'filename': LOG_DIR / 'store.log', 'maxBytes': 5 * 1024 * 1024, 'backupCount': 3, 'formatter': 'verbose'},
        'mail_admins': {'level': 'ERROR', 'filters': ['require_debug_false'], 'class': 'django.utils.log.AdminEmailHandler'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'store': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['file', 'mail_admins'], 'level': 'ERROR', 'propagate': False},
    },
}
