from django.db import models


class ExportManager(models.Manager):

    def get_queryset(self) -> models.QuerySet:
        return (
            super().get_queryset()
            .select_related("config_table", "config_pdf")
        )

    def for_model(self, model_class: type[models.Model]) -> models.QuerySet:
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(model_class)
        return self.get_queryset().filter(target=ct)
