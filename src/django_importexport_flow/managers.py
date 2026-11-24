from __future__ import annotations

from typing import cast

from django.db import models


class DefinitionQuerySet(models.QuerySet):
    def exports(self) -> DefinitionQuerySet:
        return cast('DefinitionQuerySet', self.filter(direction='export'))

    def imports(self) -> DefinitionQuerySet:
        return cast('DefinitionQuerySet', self.filter(direction='import'))


class DefinitionManager(models.Manager):
    def get_queryset(self) -> DefinitionQuerySet:
        return (
            DefinitionQuerySet(model=self.model, using=self._db)
            .annotate(step_count=models.Count('steps', distinct=True))
            .prefetch_related('category_configs__format_configs')
        )

    def has_steps(self, definition_id: object) -> bool:
        """Check the current step count rather than a stale model annotation."""
        count = (
            self.get_queryset()
            .filter(pk=definition_id)
            .values_list('step_count', flat=True)
            .get()
        )
        return count > 0

    def for_model(self, model_class: type[models.Model]) -> DefinitionQuerySet:
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(model_class)
        return cast('DefinitionQuerySet', self.get_queryset().filter(target=ct))

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
