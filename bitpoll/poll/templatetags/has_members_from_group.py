from django import template

register = template.Library()

# Returns true if the given poll has a member of the argument group_name
@register.filter
def has_members_from_group(poll, group_name):
    return (
        poll.vote_set.filter(user__groups__name=group_name).exists()
        or poll.invitation_set.filter(user__groups__name=group_name).exists()
    )
