from rest_framework import serializers

from .models import BitpollUser
from django.contrib.auth.models import Group
from allauth.socialaccount.models import SocialAccount


class UserSerializer(serializers.HyperlinkedModelSerializer):
    groups = serializers.SlugRelatedField(
        many=True, slug_field="name", queryset=Group.objects.all()
    )
    last_login = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S%z", required=False)
    date_joined = serializers.DateTimeField(
        format="%Y-%m-%dT%H:%M:%S%z", required=False
    )

    class Meta:
        model = BitpollUser
        fields = [
            "id",
            "url",
            "username",
            "email",
            "first_name",
            "last_name",
            "groups",
            "is_active",
            "date_joined",
            "last_login",
        ]
        lookup_field = "username"
        extra_kwargs = {"url": {"lookup_field": "username"}}


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["url", "name"]
        lookup_field = "name"
        extra_kwargs = {"url": {"lookup_field": "name"}}


class SocialAccountSerializer(serializers.HyperlinkedModelSerializer):
    user = serializers.SlugRelatedField(
        many=False, slug_field="username", queryset=BitpollUser.objects.all()
    )

    class Meta:
        model = SocialAccount
        fields = ["url", "user", "provider", "uid"]
        lookup_field = "uid"
        extra_kwargs = {
            "url": {"lookup_field": "uid"},
            # 'user': {'lookup_field': 'user'},
        }
