from django import template

register = template.Library()


@register.filter
def user_groups(user):
    return user.groups.values_list("name", flat=True)
