from django.apps import AppConfig


class NextcloudAuthenticatorConfig(AppConfig):
    name = "bitpoll.nextcloud_authenticator"

    def ready(self):
        # register post-login signals
        from bitpoll.nextcloud_authenticator import signals
