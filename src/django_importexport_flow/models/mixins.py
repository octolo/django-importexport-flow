from django.db import models
from django.utils.translation import gettext_lazy as _


class ProcessingBackendMixin(models.Model):
    processing_backend = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Processing backend"),
        help_text=_(
            "Optional dotted import path (e.g. myapp.tasks.run_import) or a method name "
            "on the target model. When empty, the built-in import/export engine is used."
        ),
    )
    processing_backend_kwargs = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Processing backend kwargs"),
        help_text=_("Keyword arguments passed to the processing backend callable."),
    )

    class Meta:
        abstract = True
