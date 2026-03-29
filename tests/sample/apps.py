from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SampleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.sample"
    label = "sample"
    verbose_name = _("Sample (demo models)")

    def ready(self) -> None:
        super().ready()
        # Ensures ModelAdmin registrations run (same effect as admin autodiscover).
        from . import admin  # noqa: F401
