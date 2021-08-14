from allauth.socialaccount.providers.nextcloud.provider import NextCloudProvider


class CustomNextCloudProvider(NextCloudProvider):
    id = "nextcloud_auth"
    
    def extract_common_fields(self, data):
        return data


provider_classes = [CustomNextCloudProvider]
