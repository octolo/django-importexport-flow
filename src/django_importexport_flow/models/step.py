from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .definition import Definition


class Step(models.Model):
    """An ordered, reusable import definition in a combined import."""

    parent = models.ForeignKey(
        Definition,
        on_delete=models.CASCADE,
        related_name='steps',
        limit_choices_to={'direction': Definition.Direction.IMPORT},
    )
    definition = models.ForeignKey(
        Definition,
        on_delete=models.PROTECT,
        related_name='used_by_steps',
        limit_choices_to={'direction': Definition.Direction.IMPORT},
    )
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ('position', 'pk')
        constraints = [
            models.UniqueConstraint(
                fields=('parent', 'position'),
                name='step_parent_position_uniq',
            ),
            models.UniqueConstraint(
                fields=('parent', 'definition'),
                name='step_parent_definition_uniq',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.position}: {self.definition}'

    def clean(self) -> None:
        super().clean()
        if (
            self.parent_id
            and self.parent.direction != Definition.Direction.IMPORT
        ):
            raise ValidationError(
                {'parent': _('Parent must be an import definition.')}
            )
        if (
            self.definition_id
            and self.definition.direction != Definition.Direction.IMPORT
        ):
            raise ValidationError(
                {'definition': _('Step must be an import definition.')}
            )
        if self.parent_id and self.parent_id == self.definition_id:
            raise ValidationError(
                {'definition': _('An import cannot contain itself.')}
            )
        if self.definition_id and self.definition.steps.exists():
            raise ValidationError(
                {'definition': _('Nested combined imports are not supported.')}
            )
        if self.parent_id and self.parent.used_by_steps.exists():
            raise ValidationError(
                {'parent': _('Nested combined imports are not supported.')}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
