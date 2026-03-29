from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoImportExportFlowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_importexport_flow"
    verbose_name = _("Django import export flow")
