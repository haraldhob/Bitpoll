# sauce: https://stackoverflow.com/a/433209
from django.conf import settings  # import the settings file


def add_settings(_):
    return {"settings": settings}
