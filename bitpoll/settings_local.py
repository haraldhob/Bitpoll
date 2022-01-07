# You must insert your own random value here
# SECURITY WARNING: keep the secret key used in production secret!
# see <https://docs.djangoproject.com/en/dev/howto/deployment/checklist/#secret-key>
SECRET_KEY = '12345678'

# generate via: ./manage.py generate_encryption_key
FIELD_ENCRYPTION_KEY = "this+is+an+example+key+please+generate+one+="

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

PIPELINE_LOCAL = {}

# If Bitpoll is served via HTTPS enable the next two options
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# The root dir bitpoll appears to be in from the web, as configured in the webserver
URL_PREFIX = ''

INSTALLED_APPS_LOCAL = [
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'bitpoll.nextcloud_authenticator',
    'django.contrib.sites',
]

LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'

## https://docs.djangoproject.com/en/1.9/ref/settings/#databases
# DATABASES = {
#    'default': {
#        'ENGINE': 'django.db.backends.sqlite3',
#        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#    }
# }

## Test mail functionality by printing mails to console:
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

## if the imprint URL is not empty use it as an link to the imprint, else use IMPRINT_TEXT
# IMPRINT_URL = ""
# IMPRINT_TEXT = """
# <h1>Impressum</h1>
# <p>Text goes here</p>
# """

# LOCALE_PATHS = (os.path.join(ROOT_DIR, 'locale'), )
# LANGUAGES = (
#    ('de', 'Deutsch'),
#    ('en', 'English'),
#    #('fr', 'Français'),
# )

REGISTER_ENABLED = False
GROUP_MANAGEMENT = False

# Because we don't want additional email confirmations, disable this feature.
ACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_SESSION_REMEMBER = True

# Used by the multi-site management system of the allauth library -> not important
SITE_ID = 1

AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin, regardless of `allauth`
    'django.contrib.auth.backends.ModelBackend',
    # django-allauth backend
    'allauth.account.auth_backends.AuthenticationBackend',
)

""" How to setup the nextcloud instance:

1. Log in with admin permissions and navigate to settings/admin/security.
2. Add a new OAuth 2.0 client at the bottom of the page (Nextcloud Version 20)
    - "Name": This can be any name.
    - "Redirection URI": This has to be the following URI (fill in the base domain):
        -> 'https://<bitpoll_domain>/accounts/nextcloud_auth/login/callback/' <-
3. Copy the "Client Identification" and paste it into the "client_id" field.
4. Copy the "Secret" and paste it into the "secret" field. 
"""
SOCIALACCOUNT_PROVIDERS = {
    'nextcloud_auth': {
        'SERVER': 'https://<nextcloud_base_url>',
        'APP': {
            "client_id": "<some_client_id>",
            "secret": "<super_secret_key>",
        },
        # emails received from nextcloud accounts are automatically marked as valid
        'VERIFIED_EMAIL': True,
    }
}

# Customize your instance
SITE_NAME = 'Bitpoll'
BASE_URL = 'https://<bitpoll_base_url>'

# Url to the Base Homepage and Text on the Link, leave empty to not use this option
HOME_URL = "https://<nextcloud_base_url>"
HOME_URL_NAME = "Nextcloud"

ALLOWED_HOSTS = [
    "localhost",
    "<bitpoll_base_url>",
]

ADMIN_GROUPS = ["admin"]

POLL_GROUP_ORDERING = ['stipendiaten', 'alumni', 'vertrauenspersonen']
POLL_GROUP_HOVER_WHITELIST = ['stipendiaten', 'alumni', 'vertrauenspersonen', 'admin', 'steuergruppe']

# TODO: configure database
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#     }
# }

TEAM_EMAIL = "mail@example.com"