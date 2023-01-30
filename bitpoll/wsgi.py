"""
WSGI config for bitpoll project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

import sys

sys.path.append("/app/")
sys.path.append("/app/env/bin")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bitpoll.settings")

application = get_wsgi_application()
