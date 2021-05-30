from allauth.socialaccount.providers.nextcloud.provider import NextCloudProvider


class CustomNextCloudProvider(NextCloudProvider):
    id = "nextcloud_auth"


provider_classes = [CustomNextCloudProvider]
