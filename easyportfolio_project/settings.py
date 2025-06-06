# In easyportfolio_project/settings.py

import os
from pathlib import Path
from dotenv import load_dotenv # Importiere load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent # BASE_DIR zeigt auf /opt/easyportfolio_django_app/

# Pfad zur .env Datei (liegt im BASE_DIR, also im Projektstamm)
DOTENV_PATH = BASE_DIR / '.env'

# Lade die .env Datei. Wenn sie nicht existiert, passiert nichts Schlimmes.
if DOTENV_PATH.exists():
    load_dotenv(dotenv_path=DOTENV_PATH, override=True)
else:
    print(f"WARNUNG: .env Datei nicht gefunden unter {DOTENV_PATH}")


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Wir holen den SECRET_KEY jetzt aus der .env Datei
# Gib einen Standardwert an, falls er in .env nicht gesetzt ist (sollte aber!)
SECRET_KEY = os.getenv('SECRET_KEY', 'ein_standard_fallback_key_falls_env_fehlt_unbedingt_aendern')

# SECURITY WARNING: don't run with debug turned on in production!
# Wir holen DEBUG jetzt aus der .env Datei. os.getenv gibt Strings zurück.
# Wir müssen den String 'True' oder 'False' in einen Boolean umwandeln.
DEBUG_ENV = os.getenv('DEBUG', 'False') # Standardmäßig False, wenn nicht in .env
DEBUG = DEBUG_ENV.lower() in ('true', '1', 't')


ALLOWED_HOSTS = []
# Wenn DEBUG=True ist, fügt Django oft automatisch 'localhost', '127.0.0.1' hinzu.
# Für den Zugriff über deine Server-IP (später für den Entwicklungs-Server auf 0.0.0.0)
# oder deine Domain (in Produktion) müssen diese hier eingetragen werden.
# Beispiel: ALLOWED_HOSTS = ['152.53.93.102', 'localhost', '127.0.0.1', 'easyportfolio.de', 'www.easyportfolio.de']
# Fürs Erste, wenn DEBUG=True, ist eine leere Liste oft okay für localhost-Zugriff.
# Wenn du den dev server mit 0.0.0.0:8000 startest, musst du ggf. deine IP hier eintragen oder '*' (was aber unsicher ist).
if DEBUG:
    ALLOWED_HOSTS.extend(['localhost', '127.0.0.1', '152.53.93.102']) # DEINE SERVER-IP HINZUGEFÜGT
else:
    # Für den späteren Produktivbetrieb (wenn DEBUG=False) solltest du hier deine Domain eintragen
    ALLOWED_HOSTS = ['easyportfolio.de', 'www.easyportfolio.de', '152.53.93.102'] 
    # Es ist gut, die IP auch für den Produktivbetrieb drin zu lassen, falls du mal direkt per IP testen musst.
    # Wenn du den Server auf 0.0.0.0 laufen lässt und über die IP zugreifen willst:
    # ALLOWED_HOSTS.append('DEINE_SERVER_IP_HIER') # z.B. '152.53.93.102'


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_q',
    'portfolio_app.apps.PortfolioAppConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'easyportfolio_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Dieses BASE_DIR / 'templates' ist wichtig
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'easyportfolio_project.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        # Wir verwenden jetzt die Werte aus der .env Datei!
        # Der ENGINE muss später auf 'django.db.backends.mysql' geändert werden,
        # sobald wir 'mysqlclient' installiert haben. Für den Moment lassen wir
        # SQLite, um zu sehen, ob die .env-Variablen gelesen werden (obwohl sie für SQLite nicht alle gebraucht werden).
        # 'ENGINE': 'django.db.backends.sqlite3',
        # 'NAME': BASE_DIR / 'db.sqlite3',
        
        # Vorbereitung für MariaDB / MySQL:
        'ENGINE': 'django.db.backends.mysql', # Dies setzen wir jetzt schon!
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': '3306', # Standard MariaDB/MySQL Port
        'OPTIONS': {
            # Manchmal nützlich für spezielle Zeichensatzanforderungen
            # 'charset': 'utf8mb4',
            # Sicherstellen, dass SSL nicht erzwungen wird, wenn es nicht konfiguriert ist (für lokale DB)
            # 'ssl_mode': 'DISABLED', # Oder spezifische SSL-Einstellungen, falls benötigt
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'de-de' # Auf Deutsch umgestellt

TIME_ZONE = 'Europe/Berlin' # Oder 'Europe/Vienna', je nachdem was du bevorzugst

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
# Hier könnten wir später einen globalen Ordner für statische Dateien definieren:
# STATICFILES_DIRS = [BASE_DIR / "static_global"]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# API Keys aus .env laden (Beispiel, wie du sie verfügbar machen kannst)
ALPHA_VANTAGE_API_KEY_SETTING = os.getenv('ALPHA_VANTAGE_API_KEY')
EODHD_API_KEY_SETTING = os.getenv('EODHD_API_KEY')


# Du kannst dann in deinem Code (z.B. in views.py) darauf zugreifen mit:
# from django.conf import settings
# api_key = settings.ALPHA_VANTAGE_API_KEY_SETTING


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'portfolio_app': { # Logger für deine App
            'handlers': ['console'],
            'level': 'DEBUG', # Zeigt DEBUG, INFO, WARNING, ERROR, CRITICAL für deine App
            'propagate': True,
        },
    },
}


# Django Q2 Settings
Q_CLUSTER = {
    'name': 'easyportfolio_q', # Ein Name für deinen Cluster
    'workers': 2,  # Anzahl der Worker-Prozesse (passe dies bei Bedarf an die CPU-Kerne deines VPS an)
    'timeout': 1800,  # Timeout für Tasks in Sekunden - 30 Min. wegen Kursdatenabfrage
    'retry': 120,  # Zeit in Sekunden, nach der ein fehlgeschlagener Task wiederholt wird
    'queue_limit': 50,  # Maximale Anzahl von Tasks in der Queue
    'bulk': 10,  # Wie viele Tasks ein Worker auf einmal holt
    'orm': 'default',  # Nutzt die 'default' Django Datenbankverbindung als Broker
    # Für bessere Performance könntest du später Redis konfigurieren:
    # 'redis': {
    #     'host': '127.0.0.1',
    #     'port': 6379,
    #     'db': 0,
    #     # 'password': 'deinredispasswort', # falls gesetzt
    #     # 'socket_timeout': None,
    #     # 'charset': 'utf-8',
    #     # 'errors': 'strict',
    #     # 'unix_socket_path': None
    # }
    'label': 'Django Q', # Label im Admin-Interface
    'log_level': 'INFO', # Logging-Level für den Q-Cluster (DEBUG, INFO, WARNING, ERROR)
    # 'catch_up': True, # Ob der Scheduler beim Start verpasste Tasks nachholt
    'scheduler': True, # Wichtig: Aktiviert den Scheduler-Teil von django-q2
}
