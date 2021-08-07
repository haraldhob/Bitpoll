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
    access_token_url = "{0}/index.php/apps/oauth2/api/v1/token".format(server)
    authorize_url = "{0}/index.php/apps/oauth2/authorize".format(server)
    profile_url = "{0}/ocs/v1.php/cloud/users/".format(server)

    def get_user_info(self, token, user_id):
        headers = {"Authorization": "Bearer {0}".format(token)}
        resp = requests.get(self.profile_url + user_id, headers=headers)
        if resp.status_code != 200:
            print("Error in user metadata request: " + str(resp.status_code) + " " + resp.content.decode())
        resp.raise_for_status()
        data = ET.fromstring(resp.content.decode())[1]

        result_dict = {}
        for d in data:
            if d.text:
                result_dict[d.tag] = d.text.strip()
            # The 'groups' tag doesn't contain plain text, but a list of group strings
            if d.tag == 'groups':
                result_dict[d.tag] = ", ".join([e.text for e in d])

        # Our login fails if the nextcloud user doesn't have a valid email. This shouldn't be the case.
        if "email" not in result_dict.keys():
            raise ValueError(f"Missing user email in nextcloud account for user {user_id}.")
        return result_dict


oauth2_login = OAuth2LoginView.adapter_view(CustomNextCloudAdapter)
oauth2_callback = OAuth2CallbackView.adapter_view(CustomNextCloudAdapter)
