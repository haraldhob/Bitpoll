from django import template

register = template.Library()

# Returns true if the given poll has a member of the argument group_name
@register.filter
def has_members_from_poll(group_list, poll):
    poll_member_group_names = list(
        poll.vote_set.values_list("user__groups__name", flat=True)
    ) + list(poll.invitation_set.values_list("user__groups__name", flat=True))
    return set(group_list).intersection(poll_member_group_names)
