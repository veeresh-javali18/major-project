from django import template

register = template.Library()

@register.filter(name='has_role')
def has_role(user, role_name):
    if not user.is_authenticated:
        return False
    return getattr(user, 'role', '') == role_name

@register.filter(name='is_doctor')
def is_doctor(user):
    if not user.is_authenticated:
        return False
    return getattr(user, 'role', '') == 'doctor'

@register.filter(name='is_patient')
def is_patient(user):
    if not user.is_authenticated:
        return False
    return getattr(user, 'role', '') == 'patient'
