"""
Django settings for biospecdb project.

Generated by 'django-admin startproject' using Django 4.1.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.1/ref/settings/
"""

from pathlib import Path
import os
import sys


PROJECT_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'apps'))


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-9ppt7g3y2ds5+nig07x(#8^th-olh5u=kr_tiqs$2*h(u!y&^m'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "nested_admin",
    "explorer",
    "uploader.apps.UploaderConfig",
    "user.apps.UserConfig"
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

AUTH_USER_MODEL = "user.User"

ROOT_URLCONF = 'biospecdb.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'biospecdb.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases

DB_DIR = "db"
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / DB_DIR / 'admin.sqlite3',
    },
    "bsr": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / DB_DIR / "bsr.sqlite3",
    }
}

# The order in which routers are processed is significant. Routers will be queried in the order they are listed here.
DATABASE_ROUTERS = ["biospecdb.routers.BSRRouter"]


# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'EST'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# SQL explorer settings.

EXPLORER_CONNECTIONS = {"data": "bsr"}
EXPLORER_DEFAULT_CONNECTION = "bsr"

EXPLORER_DEFAULT_ROWS = 1000

EXPLORER_SQL_BLACKLIST = (
     # DML
     'COMMIT',
     'DELETE',
     'INSERT',
     'MERGE',
     'REPLACE',
     'ROLLBACK',
     'SET',
     'START',
     'UPDATE',
     'UPSERT',

     # DDL
     'ALTER',
     'CREATE',
     'DROP',
     'RENAME',
     'TRUNCATE',

     # DCL
     'GRANT',
     'REVOKE',
 )

EXPLORER_SCHEMA_EXCLUDE_TABLE_PREFIXES = (
    'auth',
    'contenttypes',
    'sessions',
    'admin',
    "django",
    "explorer"
)

EXPLORER_DATA_EXPORTERS = [
    ('csv', 'uploader.exporters.CSVExporter'),
    ('excel', 'uploader.exporters.ExcelExporter'),
    ('json', 'uploader.exporters.JSONExporter')
]

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'biospecdb/apps/uploader/templates/static')]

EXPLORER_SCHEMA_INCLUDE_VIEWS = True

EXPLORER_CHARTS_ENABLED = True

# NOTE: The following two settings don't actually belong to explorer.

# Include the spectral data files, if present in query results, for download as zip file.
EXPLORER_DATA_EXPORTERS_INCLUDE_DATA_FILES = True
# Exhaustively scan query result values for relevant filepaths to collect data files. Does nothing when
# EXPLORER_DATA_EXPORTERS_INCLUDE_DATA_FILES == False.
EXPLORER_DATA_EXPORTERS_ALLOW_DATA_FILE_ALIAS = False

# Custom settings:

# Automatically run "default" annotators when new spectral data is saved. Note: Annotators are always run when new
# annotations are explicitly created and saved regardless of the below setting.
AUTO_ANNOTATE = True

# Run newly added/updated annotator on all spectral data if annotator.default is True.
# WARNING: This may be time-consuming if the annotators takes a while to run and there are a lot of
# spectral data samples in the database.
RUN_DEFAULT_ANNOTATORS_WHEN_SAVED = False

# Disable this class for now as #69 made it obsolete, however, there's a very good chance it will be needed
# when implementing background tasks for https://github.com/ssec-jhu/biospecdb/pull/77.
DISABLE_QC_MANAGER = True

# Auto-populate the model field ``Visit.previous_visit`` by searching for existing older visits and choosing the last.
# WARNING! This may give incorrect results.
AUTO_FIND_PREVIOUS_VISIT = True
