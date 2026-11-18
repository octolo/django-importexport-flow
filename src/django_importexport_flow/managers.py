from __future__ import annotations

from typing import cast

from django.db import models


class DefinitionQuerySet(models.QuerySet):
    def exports(self) -> DefinitionQuerySet:
        return cast("DefinitionQuerySet", self.filter(direction="export"))

    def imports(self) -> DefinitionQuerySet:
        return cast("DefinitionQuerySet", self.filter(direction="import"))


class DefinitionManager(models.Manager):
    def get_queryset(self) -> DefinitionQuerySet:
        return DefinitionQuerySet(model=self.model, using=self._db).prefetch_related(
            "category_configs__format_configs"
        )

    def for_model(self, model_class: type[models.Model]) -> DefinitionQuerySet:
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(model_class)
        return cast("DefinitionQuerySet", self.get_queryset().filter(target=ct))

    def exports(self) -> DefinitionQuerySet:
        return self.get_queryset().exports()

    def imports(self) -> DefinitionQuerySet:
        return self.get_queryset().imports()


class ExportDefinitionManager(DefinitionManager):
    def get_queryset(self) -> DefinitionQuerySet:
        return super().get_queryset().exports()


class ImportDefinitionManager(DefinitionManager):
    def get_queryset(self) -> DefinitionQuerySet:
        return super().get_queryset().imports()


ExportManager = ExportDefinitionManager
