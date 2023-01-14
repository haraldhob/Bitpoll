from django import template

register = template.Library()

# Turn snake_case strings to Title Case
@register.filter
def snake_to_title(s):
    return s.replace("_", " ").title()
