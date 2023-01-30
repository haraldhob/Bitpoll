from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.urls import reverse


class AuthRequiredMiddleware(AuthenticationMiddleware):
    allowed_parts = {
        "api/",
        "admin/",
        reverse("login"),
    }

    def process_request(self, request):
        if not request.user.is_authenticated:
            if not any(
                part in request.path for part in self.allowed_parts
            ) and settings.LOGIN_URL not in request.build_absolute_uri(request.path):
                return redirect_to_login(request.get_full_path())
        return None
