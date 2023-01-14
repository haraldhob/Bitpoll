from django import template

register = template.Library()

# Get nth - 1 element from list
@register.filter
def nth_prev(l, n):
    return l[n - 1]
