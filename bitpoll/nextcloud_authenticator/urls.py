from allauth.socialaccount.providers.oauth2.urls import default_urlpatterns

from .provider import CustomNextCloudProvider


urlpatterns = default_urlpatterns(CustomNextCloudProvider)
