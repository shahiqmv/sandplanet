from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from django.db.models.signals import post_save

        from . import checks  # noqa: F401  — registers the deploy checks
        from .models import Site

        def _site_saved(sender, instance, **kw):
            # A customer that is this site's client follows its client block
            # (MARINE_BUILD_BRIEF.md: customers vs clients, owner 2026-09-25).
            from .rental import sync_client_customers
            sync_client_customers(instance)
        post_save.connect(_site_saved, sender=Site, weak=False, dispatch_uid="site-client-customers")
