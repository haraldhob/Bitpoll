from allauth.socialaccount.signals import social_account_updated
from allauth.account.signals import user_signed_up

from django.contrib.auth.models import Group
from django.dispatch import receiver
from django.conf import settings

from bitpoll.groups.models import create_usergroup, GroupProxy


@receiver(user_signed_up)
@receiver(social_account_updated)
def user_login_callback(**kwargs):
    """
    Process group data on user login.

    This is not supported by default for the django-allauth login process. Therefore, we use signals to post-process
    the logged in user. This callback is called if either a user was created (-> user_signed_up) or the user already had
    an existing account and the new information can be used for updates (-> social_account_updated).
    """
    social_login = kwargs['sociallogin']
    user_groups = social_login.account.extra_data['groups'].split(", ")

    for group in user_groups:
        local_group = Group.objects.filter(name=group)
        # create a new group if it doesn't exist locally
        if not local_group.exists():
            create_usergroup(social_login.user, group)

        # the group does exist, but either the user doesn't exist, or the existing user is not a member of the group
        elif not social_login.is_existing or not local_group[0].user_set.filter(id=social_login.user.id).exists():
            GroupProxy(local_group[0]).add_member(social_login.user)

        if group in settings.ADMIN_GROUPS:
            social_login.user.is_superuser = True
            social_login.user.is_staff = True
            social_login.user.save()

    # afterwards, if the user was previously existing, update its membership in all existing groups
    if social_login.is_existing:
        for group in Group.objects.all():
            gp = GroupProxy(group)
            if group.name not in user_groups and gp.is_member(social_login.user):
                gp.remove_member(social_login.user)
