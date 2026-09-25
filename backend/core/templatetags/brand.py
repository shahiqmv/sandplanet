"""`{% load brand %}` … `{% brand primary %}` — a brand colour inside a PDF
template, from the company's parameters (MARINE_BUILD_BRIEF.md §2). The
Sand Planet defaults are the literals the templates carried before."""
from django import template

from .. import brand as brand_svc

register = template.Library()


@register.simple_tag(name="brand")
def brand_tag(token):
    return brand_svc.colour(token)
