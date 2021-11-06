from django.conf.urls import url
from django.urls import path, include

from rest_framework import routers

from . import views

router = routers.DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'groups', views.GroupViewSet)
router.register(r'social_account', views.SocialAccountViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    url(r'^settings/$', views.user_settings, name='settings'),
    url(r'^$', views.index, name='index'),
    url(r'^imprint/$', views.imprint, name='imprint'),
    url(r'^about/$', views.about, name='about'),
    url(r'^licenses/$', views.licenses, name='base_licenses'),
    url(r'^technical_info/$', views.tecnical, name='technical'),
    url(r'^autocomplete$', views.autocomplete, name='base_autocomplete'),
    url(r'^problems$', views.problems, name='base_problems'),
]
