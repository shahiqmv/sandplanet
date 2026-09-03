"""Render a PDF once per version of its content.

IPA-02 on MXR A,C&F is 38 pages and 1,517 valued lines. WeasyPrint lays it
out in 40-odd seconds on the production box, and measuring showed the
template is not the lever: removing the per-row page-break rule, fixing the
table layout and splitting it into 24 tables all came out the same or worse,
while the summary pages alone take 0.75 s. The detail table simply costs what
it costs (owner 2026-09-03, "took more than 15 seconds").

So the document is rendered once and kept. The key is the SHA-1 of the
rendered HTML: any change to the data, the template or the company details
changes the HTML and so the key, and there is no invalidation logic to get
wrong. Files live in default_storage — object storage in production — so
they survive deploys and are shared by every worker.
"""
import hashlib
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.template.loader import render_to_string

log = logging.getLogger("core.pdf_cache")
PREFIX = "pdf/cache/"


def html_key(html):
    return hashlib.sha1(html.encode("utf-8")).hexdigest()


def cached_pdf(html, *, warm_only=False):
    """PDF bytes for `html`, from the cache if that exact HTML has been
    rendered before. `warm_only` renders and stores without returning the
    bytes to a caller that does not need them."""
    from weasyprint import HTML

    name = f"{PREFIX}{html_key(html)}.pdf"
    if default_storage.exists(name):
        if warm_only:
            return None
        with default_storage.open(name, "rb") as fh:
            return fh.read()
    pdf = HTML(string=html, base_url=str(settings.MEDIA_ROOT)).write_pdf()
    try:
        default_storage.save(name, ContentFile(pdf))
    except Exception:                       # pragma: no cover - storage hiccup
        log.exception("could not store rendered PDF %s", name)
    return None if warm_only else pdf


def render_cached(template, context, **kw):
    return cached_pdf(render_to_string(template, context), **kw)
