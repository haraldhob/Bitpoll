from rest_framework import serializers

from .models import BitpollUser
from django.contrib.auth.models import Group

class UserSerializer(serializers.HyperlinkedModelSerializer):
    groups = serializers.SlugRelatedField(many=True, slug_field='name', queryset=Group.objects.all())
    class Meta:
        model = BitpollUser
        fields = ['id', 'url', 'username', 'email', 'first_name', 'last_name', 'groups']


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ['url', 'name']
        lookup_field = 'name'
        extra_kwargs = {
            'url': {'lookup_field': 'name'}
        }