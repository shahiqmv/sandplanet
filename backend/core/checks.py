"""Production-surface checks — run by `manage.py check --deploy`.

A site PM landed on Django REST framework's browsable API: a form-filled
developer page, rendered under the company's name, because a browser had
navigated to an API URL (owner 2026-09-02). The same day's audit found the
Django admin mounted publicly and never once used. Each is one instance of a
class — a framework's own developer surface reachable by the people we serve —
and the owner's question was how to make the class impossible, not the
instance.

These checks are the answer. They are tagged `deploy`, so `check --deploy`
runs them, and entrypoint.sh runs that with --fail-level WARNING before the
container will start: a regression is not a bug somebody notices later, it is
a deploy that does not happen. tests_hardening runs the same functions so CI
fails first.
"""
from django.conf import settings
from django.core.checks import Error, Tags, register

# Apps that exist to expose internals — fine on a laptop, never on the box.
DEVELOPER_APPS = ("debug_toolbar", "django_extensions", "drf_spectacular",
                  "drf_yasg", "silk", "rest_framework_swagger")
# DRF renderers that draw HTML pages. JSON is the only thing the API speaks.
HTML_RENDERERS = ("BrowsableAPIRenderer", "TemplateHTMLRenderer",
                  "AdminRenderer", "StaticHTMLRenderer",
                  "DocumentationRenderer")


def _walk(patterns, prefix=""):
    from django.urls import URLPattern, URLResolver
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route, p.callback


def _renderer_names(callback):
    view = getattr(callback, "cls", None) or getattr(callback, "view_class",
                                                    None)
    classes = getattr(view, "renderer_classes", None) or []
    return [c.__name__ for c in classes]


@register(Tags.security, deploy=True)
def api_renders_json_only(app_configs, **kwargs):
    """The API must never draw an HTML page — globally or on any one view."""
    from django.urls import get_resolver
    errors = []
    default = [c.rsplit(".", 1)[-1] for c in
               settings.REST_FRAMEWORK.get("DEFAULT_RENDERER_CLASSES", [])]
    if default != ["JSONRenderer"]:
        errors.append(Error(
            f"REST_FRAMEWORK DEFAULT_RENDERER_CLASSES is {default}; it must "
            f"be exactly ['JSONRenderer'].",
            hint="The browsable API is a developer page. Users reached it.",
            id="core.E001"))
    for route, callback in _walk(get_resolver().url_patterns):
        bad = [n for n in _renderer_names(callback) if n in HTML_RENDERERS]
        if bad:
            errors.append(Error(
                f"View for '{route}' declares HTML renderer(s) {bad}.",
                id="core.E002"))
    return errors


@register(Tags.security, deploy=True)
def no_admin_site(app_configs, **kwargs):
    """The Django admin is not part of this product. It was mounted at
    /admin/ for two months, reachable by anyone, and used zero times."""
    from django.urls import get_resolver
    for route, callback in _walk(get_resolver().url_patterns):
        mod = getattr(callback, "__module__", "") or ""
        if mod.startswith("django.contrib.admin"):
            return [Error(f"The Django admin is mounted at '{route}'.",
                          hint="Remove admin.site.urls from config/urls.py.",
                          id="core.E003")]
    return []


@register(Tags.security, deploy=True)
def no_developer_apps(app_configs, **kwargs):
    found = [a for a in settings.INSTALLED_APPS
             if a.split(".")[0] in DEVELOPER_APPS]
    if found:
        return [Error(f"Developer app(s) installed: {found}.", id="core.E004")]
    return []


@register(Tags.security, deploy=True)
def debug_is_off(app_configs, **kwargs):
    """Django reports this as a warning (W018). Here it is an error: DEBUG on
    shows every visitor the settings, the URLconf and the traceback."""
    if settings.DEBUG:
        return [Error("DEBUG is True.", hint="Set DJANGO_DEBUG=0.",
                      id="core.E005")]
    return []
