import requests
import xml.etree.ElementTree as ET
from allauth.socialaccount import app_settings
from allauth.socialaccount.providers.nextcloud.views import NextCloudAdapter
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)

from .provider import CustomNextCloudProvider


class CustomNextCloudAdapter(NextCloudAdapter):
    """
    Extended NextCloud OAuth2:

    Includes group information received from the nextcloud API in the user info data ("extra_data").
    """
    provider_id = CustomNextCloudProvider.id
    settings = app_settings.PROVIDERS.get(provider_id, {})
    server = settings.get("SERVER", "https://nextcloud.example.org")
    access_token_url = "{0}/apps/oauth2/api/v1/token".format(server)
    authorize_url = "{0}/apps/oauth2/authorize".format(server)
    profile_url = "{0}/ocs/v1.php/cloud/users/".format(server)

    def get_user_info(self, token, user_id):
        headers = {"Authorization": "Bearer {0}".format(token)}
        resp = requests.get(self.profile_url + user_id, headers=headers)
        resp.raise_for_status()
        data = ET.fromstring(resp.content.decode())[1]

        result_dict = {}
        for d in data:
            if d.text:
                result_dict[d.tag] = d.text.strip()
            # The 'groups' tag doesn't contain plain text, but a list of group strings
            if d.tag == 'groups':
                result_dict[d.tag] = ", ".join([e.text for e in d])
        return result_dict


oauth2_login = OAuth2LoginView.adapter_view(CustomNextCloudAdapter)
oauth2_callback = OAuth2CallbackView.adapter_view(CustomNextCloudAdapter)
